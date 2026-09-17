"""Turn a user-typed domain/email into a scan the report screens can show.

Every web query runs a FRESH live scan — the same passive collectors as
``karne scan`` (email + transport), stored and scored — and returns its new scan
id. Each scan is a new record (rule 5), so this only ever appends.

The one exception is the abuse guard (PLAN.md K-14): the public "scan any domain"
endpoint must not let the server be used to flood third parties with DNS/HTTP.
So (1) a domain scanned ad-hoc within ``[web].rescan_cooldown_seconds`` is not
rescanned — the visitor gets that just-taken measurement; (2) a second query for a
domain that is being scanned right now waits for that scan instead of starting
another; (3) at most ``[web].max_concurrent_scans`` live scans run at once, beyond
which the query is refused with ``ScanBusy``. No IP address is recorded. These
limits are per process, so the server runs a single uvicorn worker.

The live scan is synchronous; the "measuring…" screen (§ 8.1) is rendered first
by the web layer and this scan runs behind it. Scanning is passive and
public-data only (K-07).
"""

from __future__ import annotations

import contextlib
import re
import threading
from datetime import timedelta
from typing import Any

from karne import batch, storage
from karne.analyze import rescore, scoring
from karne.collectors import dns_email
from karne.web import reports

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

# Fallbacks only; the operative values live in config/settings.toml [web].
_DEFAULT_COOLDOWN_SECONDS = 600
_DEFAULT_MAX_CONCURRENT = 4

__all__ = [
    "ScanBusy",
    "normalize_domain",
    "extract_email_domain",
    "run_live_scan",
    "web_limits",
]


class ScanBusy(Exception):
    """Every live-scan slot is taken; the visitor should try again shortly."""


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


def web_limits(settings: dict[str, Any]) -> tuple[int, int]:
    """(rescan cooldown seconds, max concurrent live scans) from settings [web]."""
    web = settings.get("web", {})
    cooldown = int(web.get("rescan_cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS))
    max_concurrent = int(web.get("max_concurrent_scans", _DEFAULT_MAX_CONCURRENT))
    return max(cooldown, 0), max(max_concurrent, 1)


class _Guard:
    """Process-wide live-scan bookkeeping: a slot counter and in-flight domains."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._inflight: dict[str, threading.Event] = {}

    def claim(self, domain: str, max_concurrent: int) -> threading.Event | None:
        """Claim a slot for ``domain``.

        Returns None when this caller owns the scan, or the Event of a scan of the
        same domain already running (the caller should wait on it). Raises
        ScanBusy when no slot is free.
        """
        with self._lock:
            running = self._inflight.get(domain)
            if running is not None:
                return running
            if self._active >= max_concurrent:
                raise ScanBusy(domain)
            self._active += 1
            self._inflight[domain] = threading.Event()
            return None

    def release(self, domain: str) -> None:
        with self._lock:
            self._active -= 1
            event = self._inflight.pop(domain, None)
        if event is not None:
            event.set()


_guard = _Guard()

# Longest a follower waits for an in-flight scan of the same domain before giving
# up and running the normal path (which then finds that scan, or scans itself).
_FOLLOW_TIMEOUT_SECONDS = 90


def _recent_scan_id(domain: str, cooldown_seconds: int) -> int | None:
    if cooldown_seconds <= 0 or not reports.DB_PATH.exists():
        return None
    conn = storage.connect(reports.DB_PATH)
    try:
        since = storage.utcnow() - timedelta(seconds=cooldown_seconds)
        return storage.latest_adhoc_scan_since(conn, domain, since)
    finally:
        conn.close()


def _scan_and_store(domain: str, settings: dict[str, Any]) -> int:
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


def run_live_scan(domain: str) -> int:
    """Collect (email + transport), store, and score a domain; return the scan id.

    Within the cooldown the just-taken ad-hoc scan is returned instead (K-14).
    Raises ScanBusy when every live-scan slot is taken.
    """
    settings = dns_email.load_settings()
    cooldown, max_concurrent = web_limits(settings)

    recent = _recent_scan_id(domain, cooldown)
    if recent is not None:
        return recent

    running = _guard.claim(domain, max_concurrent)
    if running is not None:
        running.wait(_FOLLOW_TIMEOUT_SECONDS)
        recent = _recent_scan_id(domain, cooldown)
        if recent is not None:
            return recent
        running = _guard.claim(domain, max_concurrent)
        if running is not None:  # still (or again) in flight: do not start a duplicate
            raise ScanBusy(domain)

    try:
        return _scan_and_store(domain, settings)
    finally:
        _guard.release(domain)
