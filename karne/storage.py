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
# v2 (Sprint 2): scans.run_label — the batch round a scan belongs to (PLAN.md K-09/K-11).
SCHEMA_VERSION = 2

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
    error           TEXT,              -- failure detail; NULL on success
    run_label       TEXT               -- batch round (e.g. "2026-11"); NULL for ad-hoc scans
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


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table});")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent migrations for databases created by an older schema.

    Only adds columns/indexes; never drops or rewrites data (rule 5). Safe to run
    on every startup — each step is guarded by a presence check.
    """
    # v2: scans.run_label (batch round). Absent on v1 databases.
    if "run_label" not in _table_columns(conn, "scans"):
        conn.execute("ALTER TABLE scans ADD COLUMN run_label TEXT;")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_run_label ON scans(run_label);")


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema if absent, apply additive migrations, record the version."""
    conn.executescript(_SCHEMA)
    _migrate(conn)
    # Record the current schema version if this database has not reached it yet.
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version;").fetchone()
    current = row["v"]
    if current is None or current < SCHEMA_VERSION:
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
        run_label=row["run_label"],
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
        "config_hash, consent_state, status, error, run_label) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (
            scan.domain_id,
            _iso(scan.started_at),
            _iso(scan.finished_at),
            scan.scanner_version,
            scan.config_hash,
            scan.consent_state,
            scan.status,
            scan.error,
            scan.run_label,
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


# Statuses that mark a domain "already done" within a run (resume skips these).
# ok = every collector ran; partial = a collector raised (a code-path failure that
# a re-run would not fix). running/error/absent -> the domain is (re)scanned.
DONE_STATUSES = ("ok", "partial")


def select_domains_to_scan(
    conn: sqlite3.Connection,
    run_label: str,
    *,
    sector: str | None = None,
    limit: int | None = None,
    done_statuses: tuple[str, ...] = DONE_STATUSES,
) -> list[Domain]:
    """Domains still pending for ``run_label`` (resume: PLAN.md K-09).

    Returns frame domains that do NOT yet have a scan in this run whose status is
    one of ``done_statuses``. Optionally filtered by ``sector`` and capped by
    ``limit``. Deterministic order (by id) so a resumed run is reproducible.
    """
    placeholders = ",".join("?" for _ in done_statuses)
    params: list[object] = [run_label, *done_statuses]
    sql = (
        "SELECT * FROM domains d WHERE NOT EXISTS ("
        "  SELECT 1 FROM scans s WHERE s.domain_id = d.id "
        f"  AND s.run_label = ? AND s.status IN ({placeholders})"
        ")"
    )
    if sector is not None:
        sql += " AND d.sector = ?"
        params.append(sector)
    sql += " ORDER BY d.id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_domain(r) for r in rows]


def run_status_counts(
    conn: sqlite3.Connection, run_label: str, *, sector: str | None = None
) -> dict[str, int]:
    """Count scans in ``run_label`` grouped by status (progress/resume summary).

    Counts scan rows, not domains; a domain re-scanned within a run contributes
    more than once. For the "how many domains are done" figure use
    :func:`count_done_domains`.
    """
    sql = (
        "SELECT s.status AS status, COUNT(*) AS n FROM scans s "
        "JOIN domains d ON d.id = s.domain_id WHERE s.run_label = ?"
    )
    params: list[object] = [run_label]
    if sector is not None:
        sql += " AND d.sector = ?"
        params.append(sector)
    sql += " GROUP BY s.status;"
    return {row["status"]: row["n"] for row in conn.execute(sql, params)}


def count_done_domains(
    conn: sqlite3.Connection,
    run_label: str,
    *,
    sector: str | None = None,
    done_statuses: tuple[str, ...] = DONE_STATUSES,
) -> int:
    """Distinct domains already completed in ``run_label`` (for resume reporting)."""
    placeholders = ",".join("?" for _ in done_statuses)
    sql = (
        "SELECT COUNT(DISTINCT s.domain_id) AS n FROM scans s "
        "JOIN domains d ON d.id = s.domain_id "
        f"WHERE s.run_label = ? AND s.status IN ({placeholders})"
    )
    params: list[object] = [run_label, *done_statuses]
    if sector is not None:
        sql += " AND d.sector = ?"
        params.append(sector)
    row = conn.execute(sql, params).fetchone()
    return row["n"]


def count_domains(conn: sqlite3.Connection, *, sector: str | None = None) -> int:
    """Total frame domains (optionally filtered by sector)."""
    sql = "SELECT COUNT(*) AS n FROM domains"
    params: list[object] = []
    if sector is not None:
        sql += " WHERE sector = ?"
        params.append(sector)
    return conn.execute(sql, params).fetchone()["n"]


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


def latest_adhoc_scan_since(conn: sqlite3.Connection, domain: str, since: datetime) -> int | None:
    """Id of the newest ad-hoc (run_label NULL) scan of a domain started at/after ``since``.

    Round scans are excluded: a round may carry only some dimensions (e.g. the
    email-only 2026-09 round), so it is never a stand-in for a live web query.
    """
    row = conn.execute(
        "SELECT s.id FROM scans s JOIN domains d ON d.id = s.domain_id "
        "WHERE d.domain = ? AND s.run_label IS NULL AND s.started_at >= ? "
        "ORDER BY s.started_at DESC, s.id DESC LIMIT 1;",
        (domain, _iso(since)),
    ).fetchone()
    return row["id"] if row is not None else None


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


def select_scans_for_scoring(
    conn: sqlite3.Connection,
    *,
    run_label: str | None = None,
    only_unscored: bool = False,
    dimension: str = "email",
    collector: str = "dns_email",
) -> list[int]:
    """Scan ids that have a raw ``collector`` payload and can be (re)scored.

    Filters (combinable): ``run_label`` restricts to one batch round;
    ``only_unscored`` restricts to scans with no ``scores`` row for ``dimension``.
    Scores/findings are derived (K-02), so re-scoring an already-scored scan is
    safe; ``only_unscored`` is for incremental runs. Ordered by scan id.
    """
    sql = [
        "SELECT s.id AS id FROM scans s",
        "JOIN scan_results sr ON sr.scan_id = s.id AND sr.collector = ?",
    ]
    params: list[object] = [collector]
    where: list[str] = []
    if run_label is not None:
        where.append("s.run_label = ?")
        params.append(run_label)
    if only_unscored:
        where.append(
            "NOT EXISTS (SELECT 1 FROM scores sc WHERE sc.scan_id = s.id AND sc.dimension = ?)"
        )
        params.append(dimension)
    if where:
        sql.append("WHERE " + " AND ".join(where))
    sql.append("ORDER BY s.id;")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return [row["id"] for row in rows]


def delete_scoring_for_dimension(
    conn: sqlite3.Connection, scan_id: int, dimension: str, code_prefix: str
) -> tuple[int, int]:
    """Remove a scan's derived rows for one dimension so it can be re-scored.

    Deletes the ``scores`` row(s) for ``dimension`` and the ``findings`` whose
    ``code`` starts with ``code_prefix`` (finding codes are dimension-prefixed,
    e.g. ``EMAIL_``), leaving other dimensions' derived rows intact. Never touches
    ``scan_results`` (rule 5 / K-02). Returns (scores_deleted, findings_deleted).
    """
    cur = conn.execute(
        "DELETE FROM scores WHERE scan_id = ? AND dimension = ?;",
        (scan_id, dimension),
    )
    n_scores = cur.rowcount
    cur = conn.execute(
        "DELETE FROM findings WHERE scan_id = ? AND code LIKE ?;",
        (scan_id, code_prefix + "%"),
    )
    n_findings = cur.rowcount
    return n_scores, n_findings
