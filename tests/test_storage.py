"""Tests for the SQLite storage layer, run against a temporary database file."""

from __future__ import annotations

import sqlite3

import pytest

from karne import storage
from karne.models import (
    STATUS_OK,
    STATUS_RUNNING,
    DnsRecord,
    Domain,
    Finding,
    Scan,
    ScanResult,
    Score,
)

EXPECTED_TABLES = {
    "schema_version",
    "domains",
    "scans",
    "scan_results",
    "dns_records",
    "cookies",
    "requests",
    "scores",
    "findings",
}


@pytest.fixture
def conn(tmp_path):
    """A connected, initialised database on a real temp file (WAL needs a file)."""
    connection = storage.connect(tmp_path / "karne.db")
    storage.init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()
    return {r["name"] for r in rows}


# ---------------------------------------------------------------------------
# Frame domains (Sprint 1): bulk upsert + sector counts
# ---------------------------------------------------------------------------


def test_add_domains_inserts_new(conn):
    result = storage.add_domains(
        conn,
        [
            Domain("itu.edu.tr", source="tranco", sector="university", is_public_body=True),
            Domain(
                "mumifashion.com", source="curated_tr_com", sector="ecommerce", is_public_body=False
            ),
        ],
    )
    assert result == {"added": 2, "updated": 0, "total": 2}
    row = storage.get_domain(conn, "itu.edu.tr")
    assert row.sector == "university" and row.is_public_body is True
    assert row.added_at is not None


def test_add_domains_refreshes_existing_but_keeps_added_at(conn):
    storage.add_domains(conn, [Domain("x.com.tr", source="tranco", sector="unknown")])
    first = storage.get_domain(conn, "x.com.tr")
    # Re-run with a refined label: metadata updates, added_at is preserved.
    result = storage.add_domains(
        conn, [Domain("x.com.tr", source="tranco", sector="bank", is_public_body=False)]
    )
    assert result == {"added": 0, "updated": 1, "total": 1}
    row = storage.get_domain(conn, "x.com.tr")
    assert row.sector == "bank"
    assert row.added_at == first.added_at


def test_add_domains_dedups_within_batch(conn):
    result = storage.add_domains(
        conn,
        [
            Domain("dup.edu.tr", source="tranco", sector="university"),
            Domain("dup.edu.tr", source="tranco", sector="university"),
        ],
    )
    assert result["added"] == 1
    assert conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0] == 1


def test_domain_sector_counts(conn):
    storage.add_domains(
        conn,
        [
            Domain("a.edu.tr", sector="university"),
            Domain("b.edu.tr", sector="university"),
            Domain("c.gov.tr", sector="public_body"),
        ],
    )
    counts = storage.domain_sector_counts(conn)
    assert counts["university"] == 2
    assert counts["public_body"] == 1


# ---------------------------------------------------------------------------
# Schema / connection
# ---------------------------------------------------------------------------


def test_init_creates_all_tables(conn):
    assert _table_names(conn) >= EXPECTED_TABLES


def test_schema_version_recorded(conn):
    assert storage.schema_version(conn) == storage.SCHEMA_VERSION


def test_init_is_idempotent(tmp_path):
    connection = storage.connect(tmp_path / "karne.db")
    storage.init_db(connection)
    storage.init_db(connection)  # second call must not fail or double-insert
    rows = connection.execute("SELECT COUNT(*) AS n FROM schema_version;").fetchone()
    assert rows["n"] == 1
    connection.close()


def test_wal_mode_enabled(conn):
    mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"


def test_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------


def test_get_or_create_domain_creates_once(conn):
    first = storage.get_or_create_domain(conn, "example.com", source="manual")
    assert first.id is not None
    assert first.added_at is not None and first.added_at.tzinfo is not None

    second = storage.get_or_create_domain(conn, "example.com")
    assert second.id == first.id  # no duplicate row

    count = conn.execute("SELECT COUNT(*) AS n FROM domains;").fetchone()["n"]
    assert count == 1


def test_get_domain_roundtrip(conn):
    created = storage.get_or_create_domain(
        conn, "itu.edu.tr", source="manual", sector="university", is_public_body=True
    )
    fetched = storage.get_domain(conn, "itu.edu.tr")
    assert fetched == created
    assert fetched.is_public_body is True  # bool mapping, not int


def test_get_domain_missing_returns_none(conn):
    assert storage.get_domain(conn, "nonexistent.example") is None


# ---------------------------------------------------------------------------
# Scans lifecycle
# ---------------------------------------------------------------------------


def test_scan_lifecycle(conn):
    domain = storage.get_or_create_domain(conn, "example.com")
    scan = Scan(domain_id=domain.id, scanner_version="0.1.0")
    scan_id = storage.insert_scan(conn, scan)

    running = storage.get_scan(conn, scan_id)
    assert running.status == STATUS_RUNNING
    assert running.started_at is not None
    assert running.finished_at is None

    storage.finish_scan(conn, scan_id, status=STATUS_OK)
    finished = storage.get_scan(conn, scan_id)
    assert finished.status == STATUS_OK
    assert finished.finished_at is not None


def test_scan_requires_existing_domain(conn):
    # Foreign key is enforced: a scan for a non-existent domain must fail.
    with pytest.raises(sqlite3.IntegrityError):
        storage.insert_scan(conn, Scan(domain_id=999, scanner_version="0.1.0"))


def test_latest_scan_for_domain(conn):
    domain = storage.get_or_create_domain(conn, "example.com")
    storage.insert_scan(conn, Scan(domain_id=domain.id, scanner_version="0.1.0"))
    second = storage.insert_scan(conn, Scan(domain_id=domain.id, scanner_version="0.1.0"))
    latest = storage.latest_scan_for_domain(conn, "example.com")
    assert latest.id == second


def test_latest_adhoc_scan_since_ignores_rounds_and_old_scans(conn):
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    domain = storage.get_or_create_domain(conn, "example.com")
    since = now - timedelta(minutes=10)
    # Too old (ad-hoc, 11 minutes ago).
    storage.insert_scan(
        conn,
        Scan(domain_id=domain.id, scanner_version="0.1.0", started_at=now - timedelta(minutes=11)),
    )
    assert storage.latest_adhoc_scan_since(conn, "example.com", since) is None
    # Recent but a round scan: never a stand-in for a web query.
    storage.insert_scan(
        conn,
        Scan(
            domain_id=domain.id,
            scanner_version="0.1.0",
            started_at=now - timedelta(minutes=1),
            run_label="2026-09",
        ),
    )
    assert storage.latest_adhoc_scan_since(conn, "example.com", since) is None
    # Recent ad-hoc (whole seconds, so isoformat has no fraction) -> found.
    adhoc = storage.insert_scan(
        conn,
        Scan(domain_id=domain.id, scanner_version="0.1.0", started_at=now - timedelta(minutes=5)),
    )
    assert storage.latest_adhoc_scan_since(conn, "example.com", since) == adhoc
    assert storage.latest_adhoc_scan_since(conn, "other.com", since) is None


# ---------------------------------------------------------------------------
# Scan results (raw payload)
# ---------------------------------------------------------------------------


def _new_scan(conn) -> int:
    domain = storage.get_or_create_domain(conn, "example.com")
    return storage.insert_scan(conn, Scan(domain_id=domain.id, scanner_version="0.1.0"))


def test_scan_result_payload_roundtrip(conn):
    scan_id = _new_scan(conn)
    payload = {
        "spf": {"records": ["v=spf1 -all"], "terminator": "-all"},
        "note": "Türkçe karakter: ğüşıöç",
        "nested": {"a": [1, 2, 3], "b": None},
    }
    storage.insert_scan_result(
        conn, ScanResult(scan_id=scan_id, collector="dns_email", payload=payload)
    )

    fetched = storage.get_scan_result(conn, scan_id, "dns_email")
    assert fetched is not None
    assert fetched.payload == payload  # exact roundtrip, including non-ASCII and None


def test_scan_result_not_overwritten(conn):
    # Rule 5: raw data is never overwritten. A second payload for the same
    # (scan, collector) must be rejected, not silently replaced.
    scan_id = _new_scan(conn)
    storage.insert_scan_result(
        conn, ScanResult(scan_id=scan_id, collector="dns_email", payload={"a": 1})
    )
    with pytest.raises(sqlite3.IntegrityError):
        storage.insert_scan_result(
            conn, ScanResult(scan_id=scan_id, collector="dns_email", payload={"a": 2})
        )


# ---------------------------------------------------------------------------
# DNS records
# ---------------------------------------------------------------------------


def test_dns_records_roundtrip_and_bool_mapping(conn):
    scan_id = _new_scan(conn)
    records = [
        DnsRecord(scan_id=scan_id, rtype="DMARC", value="v=DMARC1; p=none", valid=True),
        DnsRecord(scan_id=scan_id, rtype="SPF", value="v=spf1 +all", valid=False),
        DnsRecord(
            scan_id=scan_id,
            rtype="DKIM",
            selector="google",
            value=None,
            valid=None,
            notes="nxdomain",
        ),
    ]
    storage.insert_dns_records(conn, records)

    fetched = storage.get_dns_records(conn, scan_id)
    assert len(fetched) == 3
    by_type = {r.rtype: r for r in fetched}
    assert by_type["DMARC"].valid is True
    assert by_type["SPF"].valid is False
    assert by_type["DKIM"].valid is None
    assert by_type["DKIM"].selector == "google"
    assert by_type["DKIM"].notes == "nxdomain"


# ---------------------------------------------------------------------------
# Scores & findings (derived layer)
# ---------------------------------------------------------------------------


def test_score_roundtrip(conn):
    scan_id = _new_scan(conn)
    storage.insert_score(
        conn,
        Score(scan_id=scan_id, dimension="email", raw_score=42.5, grade="C", ruleset_version="1.0"),
    )
    scores = storage.get_scores(conn, scan_id)
    assert len(scores) == 1
    assert scores[0].raw_score == 42.5
    assert scores[0].grade == "C"
    assert scores[0].ruleset_version == "1.0"


def test_finding_evidence_roundtrip(conn):
    scan_id = _new_scan(conn)
    storage.insert_finding(
        conn,
        Finding(
            scan_id=scan_id,
            code="EMAIL_NO_DMARC",
            severity="high",
            evidence={"queried": "_dmarc.example.com", "result": "nxdomain"},
            fix_hint_key="email.add_dmarc",
        ),
    )
    findings = storage.get_findings(conn, scan_id)
    assert len(findings) == 1
    assert findings[0].code == "EMAIL_NO_DMARC"
    assert findings[0].evidence == {"queried": "_dmarc.example.com", "result": "nxdomain"}


def test_finding_without_evidence(conn):
    scan_id = _new_scan(conn)
    storage.insert_finding(conn, Finding(scan_id=scan_id, code="X", severity="low"))
    findings = storage.get_findings(conn, scan_id)
    assert findings[0].evidence is None
