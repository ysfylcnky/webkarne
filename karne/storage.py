"""SQLite storage layer for Karne.

Stdlib ``sqlite3`` only, WAL mode, plain SQL, no ORM (PLAN.md K-04). This module
owns the schema and all row <-> dataclass mapping. It stores raw collector output
verbatim and never overwrites it (rules 1 and 5 in CLAUDE.md).

The schema matches PLAN.md section 5 (eight tables). In Sprint 0 only the email
dimension writes data; the ``cookies`` and ``requests`` tables exist in the schema
but are populated from Sprint 4 (dimension C).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from karne.models import DnsRecord, Domain, Finding, Scan, ScanResult, Score

# Bumped whenever the schema changes; recorded in the schema_version table.
SCHEMA_VERSION = 1

DEFAULT_DB_PATH = Path("data/karne.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domains (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    domain         TEXT NOT NULL UNIQUE,
    source         TEXT,
    sector         TEXT,
    is_public_body INTEGER,            -- boolean (0/1) or NULL if unknown
    added_at       TEXT NOT NULL       -- ISO-8601 UTC
);

CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id       INTEGER NOT NULL REFERENCES domains(id),
    started_at      TEXT NOT NULL,     -- ISO-8601 UTC
    finished_at     TEXT,              -- ISO-8601 UTC; NULL while running
    scanner_version TEXT NOT NULL,
    config_hash     TEXT,
    consent_state   TEXT,              -- dimension C only; NULL otherwise
    status          TEXT NOT NULL,     -- running/ok/partial/error
    error           TEXT               -- failure detail; NULL on success
);

-- Raw, untouchable collector output (rule 1, rule 5). One row per collector per scan.
CREATE TABLE IF NOT EXISTS scan_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id      INTEGER NOT NULL REFERENCES scans(id),
    collector    TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (scan_id, collector)
);

-- Flattened, queryable projection of observed DNS facts (source of truth stays
-- in scan_results.payload_json). `valid` is a syntactic-validity observation.
CREATE TABLE IF NOT EXISTS dns_records (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id  INTEGER NOT NULL REFERENCES scans(id),
    rtype    TEXT NOT NULL,
    selector TEXT,
    value    TEXT,
    valid    INTEGER,                  -- boolean (0/1) or NULL
    notes    TEXT
);

-- Dimension C (Sprint 4). Schema present now; not populated in Sprint 0.
CREATE TABLE IF NOT EXISTS cookies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL REFERENCES scans(id),
    name          TEXT,
    domain        TEXT,
    party         TEXT,                -- first/third
    http_only     INTEGER,
    secure        INTEGER,
    samesite      TEXT,
    lifetime_days REAL,
    consent_state TEXT
);

-- Dimension C (Sprint 4). Schema present now; not populated in Sprint 0.
CREATE TABLE IF NOT EXISTS requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL REFERENCES scans(id),
    host          TEXT,
    party         TEXT,
    resource_type TEXT,
    tracker_org   TEXT,
    country       TEXT
);

-- Derived scores (scoring layer, Sprint 3+). Re-derivable from raw data.
CREATE TABLE IF NOT EXISTS scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL REFERENCES scans(id),
    dimension       TEXT NOT NULL,
    raw_score       REAL,
    grade           TEXT,
    ruleset_version TEXT NOT NULL
);

-- Derived findings (scoring layer, Sprint 3+). Re-derivable from raw data.
CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       INTEGER NOT NULL REFERENCES scans(id),
    code          TEXT NOT NULL,
    severity      TEXT,
    evidence_json TEXT,
    fix_hint_key  TEXT
);

CREATE INDEX IF NOT EXISTS idx_scans_domain_id ON scans(domain_id);
CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON scan_results(scan_id);
CREATE INDEX IF NOT EXISTS idx_dns_records_scan_id ON dns_records(scan_id);
CREATE INDEX IF NOT EXISTS idx_scores_scan_id ON scores(scan_id);
CREATE INDEX IF NOT EXISTS idx_findings_scan_id ON findings(scan_id);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _to_bool(value: int | None) -> bool | None:
    return None if value is None else bool(value)


def _to_int(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _dumps(obj) -> str:
    # Deterministic, human-readable (keeps non-ASCII, e.g. Turkish, intact).
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Connection & schema
# ---------------------------------------------------------------------------


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection with WAL mode and foreign keys enabled.

    The parent directory is created if needed. Call :func:`init_db` once on a
    fresh database to create the schema.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if absent and record the schema version."""
    conn.executescript(_SCHEMA)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version;").fetchone()
    if row["v"] is None:
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?);",
            (SCHEMA_VERSION, _iso(utcnow())),
        )
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the highest recorded schema version, or None on a fresh database."""
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version;").fetchone()
    return row["v"] if row is not None else None


# ---------------------------------------------------------------------------
# Row -> dataclass mappers
# ---------------------------------------------------------------------------


def _row_to_domain(row: sqlite3.Row) -> Domain:
    return Domain(
        id=row["id"],
        domain=row["domain"],
        source=row["source"],
        sector=row["sector"],
        is_public_body=_to_bool(row["is_public_body"]),
        added_at=_parse_dt(row["added_at"]),
    )


def _row_to_scan(row: sqlite3.Row) -> Scan:
    return Scan(
        id=row["id"],
        domain_id=row["domain_id"],
        started_at=_parse_dt(row["started_at"]),
        finished_at=_parse_dt(row["finished_at"]),
        scanner_version=row["scanner_version"],
        config_hash=row["config_hash"],
        consent_state=row["consent_state"],
        status=row["status"],
        error=row["error"],
    )


def _row_to_scan_result(row: sqlite3.Row) -> ScanResult:
    return ScanResult(
        id=row["id"],
        scan_id=row["scan_id"],
        collector=row["collector"],
        payload=json.loads(row["payload_json"]),
    )


def _row_to_dns_record(row: sqlite3.Row) -> DnsRecord:
    return DnsRecord(
        id=row["id"],
        scan_id=row["scan_id"],
        rtype=row["rtype"],
        selector=row["selector"],
        value=row["value"],
        valid=_to_bool(row["valid"]),
        notes=row["notes"],
    )


def _row_to_score(row: sqlite3.Row) -> Score:
    return Score(
        id=row["id"],
        scan_id=row["scan_id"],
        dimension=row["dimension"],
        raw_score=row["raw_score"],
        grade=row["grade"],
        ruleset_version=row["ruleset_version"],
    )


def _row_to_finding(row: sqlite3.Row) -> Finding:
    evidence = row["evidence_json"]
    return Finding(
        id=row["id"],
        scan_id=row["scan_id"],
        code=row["code"],
        severity=row["severity"],
        evidence=json.loads(evidence) if evidence is not None else None,
        fix_hint_key=row["fix_hint_key"],
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def get_or_create_domain(
    conn: sqlite3.Connection,
    domain: str,
    *,
    source: str | None = None,
    sector: str | None = None,
    is_public_body: bool | None = None,
) -> Domain:
    """Return the existing domain row, creating it on first sight.

    Existing rows are returned as-is; the optional metadata is only applied when
    the row is created (we never overwrite existing domain metadata here).
    """
    existing = get_domain(conn, domain)
    if existing is not None:
        return existing
    added_at = utcnow()
    cur = conn.execute(
        "INSERT INTO domains (domain, source, sector, is_public_body, added_at) "
        "VALUES (?, ?, ?, ?, ?);",
        (domain, source, sector, _to_int(is_public_body), _iso(added_at)),
    )
    conn.commit()
    return Domain(
        id=cur.lastrowid,
        domain=domain,
        source=source,
        sector=sector,
        is_public_body=is_public_body,
        added_at=added_at,
    )


def add_domains(conn: sqlite3.Connection, domains: Iterable[Domain]) -> dict[str, int]:
    """Bulk-upsert frame domains in one transaction. Returns add/update counts.

    Sprint 1 helper for ``karne frontier``. New domains are inserted; for domains
    that already exist, the frame metadata (``source`` / ``sector`` /
    ``is_public_body``) is refreshed while ``added_at`` is preserved. This is the
    frame's working index, not raw measurement data — reproducibility of a given
    frame is captured by its per-run manifest, not by freezing these rows (rule 5
    protects raw ``scan_results``, which this never touches).
    """
    existing = {row["domain"] for row in conn.execute("SELECT domain FROM domains;")}
    to_insert: list[tuple] = []
    to_update: list[tuple] = []
    now = _iso(utcnow())
    seen: set[str] = set()
    for d in domains:
        if d.domain in seen:
            continue  # de-dup within the batch (last-writer would otherwise conflict)
        seen.add(d.domain)
        if d.domain in existing:
            to_update.append((d.source, d.sector, _to_int(d.is_public_body), d.domain))
        else:
            to_insert.append((d.domain, d.source, d.sector, _to_int(d.is_public_body), now))
    if to_insert:
        conn.executemany(
            "INSERT INTO domains (domain, source, sector, is_public_body, added_at) "
            "VALUES (?, ?, ?, ?, ?);",
            to_insert,
        )
    if to_update:
        conn.executemany(
            "UPDATE domains SET source = ?, sector = ?, is_public_body = ? WHERE domain = ?;",
            to_update,
        )
    conn.commit()
    return {"added": len(to_insert), "updated": len(to_update), "total": len(seen)}


def insert_scan(conn: sqlite3.Connection, scan: Scan) -> int:
    """Insert a scan row and return its id. Defaults ``started_at`` to now."""
    if scan.started_at is None:
        scan.started_at = utcnow()
    cur = conn.execute(
        "INSERT INTO scans (domain_id, started_at, finished_at, scanner_version, "
        "config_hash, consent_state, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
        (
            scan.domain_id,
            _iso(scan.started_at),
            _iso(scan.finished_at),
            scan.scanner_version,
            scan.config_hash,
            scan.consent_state,
            scan.status,
            scan.error,
        ),
    )
    conn.commit()
    scan.id = cur.lastrowid
    return scan.id


def finish_scan(
    conn: sqlite3.Connection,
    scan_id: int,
    *,
    status: str,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Mark a scan finished. Updates lifecycle metadata only — never raw data."""
    conn.execute(
        "UPDATE scans SET status = ?, error = ?, finished_at = ? WHERE id = ?;",
        (status, error, _iso(finished_at or utcnow()), scan_id),
    )
    conn.commit()


def insert_scan_result(conn: sqlite3.Connection, result: ScanResult) -> int:
    """Store a collector's raw payload verbatim. Never overwrites (rule 5)."""
    cur = conn.execute(
        "INSERT INTO scan_results (scan_id, collector, payload_json) VALUES (?, ?, ?);",
        (result.scan_id, result.collector, _dumps(result.payload)),
    )
    conn.commit()
    result.id = cur.lastrowid
    return result.id


def insert_dns_record(conn: sqlite3.Connection, record: DnsRecord) -> int:
    cur = conn.execute(
        "INSERT INTO dns_records (scan_id, rtype, selector, value, valid, notes) "
        "VALUES (?, ?, ?, ?, ?, ?);",
        (
            record.scan_id,
            record.rtype,
            record.selector,
            record.value,
            _to_int(record.valid),
            record.notes,
        ),
    )
    conn.commit()
    record.id = cur.lastrowid
    return record.id


def insert_dns_records(conn: sqlite3.Connection, records: Iterable[DnsRecord]) -> None:
    for record in records:
        insert_dns_record(conn, record)


def insert_score(conn: sqlite3.Connection, score: Score) -> int:
    cur = conn.execute(
        "INSERT INTO scores (scan_id, dimension, raw_score, grade, ruleset_version) "
        "VALUES (?, ?, ?, ?, ?);",
        (score.scan_id, score.dimension, score.raw_score, score.grade, score.ruleset_version),
    )
    conn.commit()
    score.id = cur.lastrowid
    return score.id


def insert_finding(conn: sqlite3.Connection, finding: Finding) -> int:
    evidence = _dumps(finding.evidence) if finding.evidence is not None else None
    cur = conn.execute(
        "INSERT INTO findings (scan_id, code, severity, evidence_json, fix_hint_key) "
        "VALUES (?, ?, ?, ?, ?);",
        (finding.scan_id, finding.code, finding.severity, evidence, finding.fix_hint_key),
    )
    conn.commit()
    finding.id = cur.lastrowid
    return finding.id


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_domain(conn: sqlite3.Connection, domain: str) -> Domain | None:
    row = conn.execute("SELECT * FROM domains WHERE domain = ?;", (domain,)).fetchone()
    return _row_to_domain(row) if row is not None else None


def domain_sector_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Count stored domains grouped by sector (frame verification helper)."""
    rows = conn.execute(
        "SELECT COALESCE(sector, 'unknown') AS sector, COUNT(*) AS n "
        "FROM domains GROUP BY sector ORDER BY n DESC;"
    ).fetchall()
    return {row["sector"]: row["n"] for row in rows}


def get_scan(conn: sqlite3.Connection, scan_id: int) -> Scan | None:
    row = conn.execute("SELECT * FROM scans WHERE id = ?;", (scan_id,)).fetchone()
    return _row_to_scan(row) if row is not None else None


def latest_scan_for_domain(conn: sqlite3.Connection, domain: str) -> Scan | None:
    row = conn.execute(
        "SELECT s.* FROM scans s JOIN domains d ON d.id = s.domain_id "
        "WHERE d.domain = ? ORDER BY s.started_at DESC, s.id DESC LIMIT 1;",
        (domain,),
    ).fetchone()
    return _row_to_scan(row) if row is not None else None


def get_scan_results(conn: sqlite3.Connection, scan_id: int) -> list[ScanResult]:
    rows = conn.execute(
        "SELECT * FROM scan_results WHERE scan_id = ? ORDER BY id;", (scan_id,)
    ).fetchall()
    return [_row_to_scan_result(r) for r in rows]


def get_scan_result(conn: sqlite3.Connection, scan_id: int, collector: str) -> ScanResult | None:
    row = conn.execute(
        "SELECT * FROM scan_results WHERE scan_id = ? AND collector = ?;",
        (scan_id, collector),
    ).fetchone()
    return _row_to_scan_result(row) if row is not None else None


def get_dns_records(conn: sqlite3.Connection, scan_id: int) -> list[DnsRecord]:
    rows = conn.execute(
        "SELECT * FROM dns_records WHERE scan_id = ? ORDER BY id;", (scan_id,)
    ).fetchall()
    return [_row_to_dns_record(r) for r in rows]


def get_scores(conn: sqlite3.Connection, scan_id: int) -> list[Score]:
    rows = conn.execute(
        "SELECT * FROM scores WHERE scan_id = ? ORDER BY id;", (scan_id,)
    ).fetchall()
    return [_row_to_score(r) for r in rows]


def get_findings(conn: sqlite3.Connection, scan_id: int) -> list[Finding]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE scan_id = ? ORDER BY id;", (scan_id,)
    ).fetchall()
    return [_row_to_finding(r) for r in rows]
