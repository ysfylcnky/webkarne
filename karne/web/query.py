"""Turn a user-typed domain/email into a scan the report screens can show.

Every web query runs a FRESH live scan — the same passive collectors as
``karne scan`` (email + transport), stored and scored — and returns its new scan
id. We deliberately never hand back a previously stored scan: the visitor asked
"scan this now", so they get a measurement taken now. Each scan is a new record
(rule 5), so this only ever appends.

The live scan is synchronous; the "measuring…" screen (§ 8.1) is rendered first
by the web layer and this scan runs behind it. Scanning is passive and
public-data only (K-07).
"""

from __future__ import annotations

import contextlib
import re

from karne import batch, storage
from karne.analyze import rescore, scoring
from karne.collectors import dns_email
from karne.web import reports

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

__all__ = ["normalize_domain", "extract_email_domain", "run_live_scan"]


def normalize_domain(raw: str) -> str | None:
    """Return a clean registrable domain, or None if the input is not one."""
    d = raw.strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)  # strip scheme
    d = d.split("/", 1)[0].split("?", 1)[0]  # strip path/query
    d = d.split("@")[-1]  # tolerate a pasted email
    d = d.strip().strip(".")
    if d.startswith("www."):
        d = d[4:]  # look up the registrable domain, where SPF/DMARC/etc. live
    if not d:
        return None
    with contextlib.suppress(UnicodeError, ValueError):
        d = d.encode("idna").decode("ascii")  # IDNA for non-ASCII (Turkish) domains
    return d if _DOMAIN_RE.match(d) else None


def extract_email_domain(raw: str) -> str | None:
    """Return the domain of a syntactically valid email address, else None."""
    value = raw.strip().lower()
    local, sep, domain = value.rpartition("@")
    if not sep or not local or " " in local:
        return None
    return normalize_domain(domain)


def run_live_scan(domain: str) -> int:
    """Collect (email + transport), store, and score a domain; return the scan id."""
    settings = dns_email.load_settings()
    specs = batch.resolve_specs(batch.DEFAULT_COLLECTORS)
    outcomes = batch.collect_bundle(domain, settings, specs)

    conn = storage.connect(reports.DB_PATH)
    try:
        storage.init_db(conn)
        scan_id, _status, _error = batch.store_bundle(conn, domain, outcomes, source="web")
        ruleset = scoring.load_ruleset(None)
        for dimension in ("email", "transport"):
            rescore.rescore_scans(conn, [scan_id], ruleset, dimension=dimension)
    finally:
        conn.close()
    return scan_id
