"""Batch scanning engine — apply dimension A to the whole Türkiye frame.

This is an ORCHESTRATOR, not a collector. The measurement logic lives in
``karne.collectors.dns_email``; this module only decides *which* domains to scan,
runs them in parallel under a concurrency limit, and persists each result through
the same write contract the single ``karne scan`` command uses — so ad-hoc and
batch scans produce identical raw data (CLAUDE.md rule 1, PLAN.md K-02).

Design (PLAN.md section 7, Sprint 2):

- **Scan round.** A run is identified by a ``run_label`` (default: the current
  UTC month, e.g. ``"2026-11"``), aligning with the monthly cadence of K-09. The
  label is stored on every ``scans`` row, so a longitudinal series is
  ``GROUP BY run_label`` and resume is unambiguous.
- **Resume.** Re-running the same ``run_label`` skips domains already completed in
  that round (status ok/partial) and scans the rest. A crashed/interrupted run
  therefore continues where it stopped and never leaves half-written raw data:
  each domain is one atomic write of a finished ``scans`` row plus its results.
- **Gentle by construction.** Domains are processed by a bounded thread pool
  (``[dns].concurrency``); within each domain the collector's own rate limiter
  (``[dns].rate_per_second``) paces queries. One worker per domain means a target's
  authoritative servers see only that domain's paced queries (PLAN.md section 4).
- **No silent failure (rule 6).** A collector crash on one domain is recorded as a
  scan-level ``error`` row and the run continues; DNS query failures
  (nxdomain/servfail/timeout) are normal outcomes handled inside the collector.

Network work runs in worker threads; every database write happens on the calling
thread (one connection, serialized), keeping stdlib ``sqlite3`` usage single-
threaded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from karne import __version__, storage
from karne.collectors import dns_email, tls_http
from karne.models import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    DnsRecord,
    Domain,
    Scan,
    ScanResult,
)

# Indicators a payload may carry; used only to detect a collector-code failure
# (an 'error' key set by dns_email._safe), NOT to judge measurement outcomes.
_INDICATORS = ("spf", "dmarc", "dkim", "mx", "dane", "mta_sts", "tls_rpt", "dnssec", "caa")


def default_run_label(now: datetime | None = None) -> str:
    """The current round label: UTC year-month, e.g. ``"2026-11"`` (PLAN.md K-09)."""
    return (now or datetime.now(UTC)).strftime("%Y-%m")


def scan_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Partial if any indicator's collector code raised; otherwise ok.

    DNS query failures (timeout/servfail/nxdomain) are normal measurement outcomes,
    not scan errors — the scan still completed and stored raw data.
    """
    errored = [
        name
        for name in _INDICATORS
        if isinstance(payload.get(name), dict) and "error" in payload[name]
    ]
    if not errored:
        return STATUS_OK, None
    detail = "; ".join(f"{name}: {payload[name]['error']}" for name in errored)
    return STATUS_PARTIAL, detail


def transport_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Dimension B has no partial state: the collector records network failures as
    normal outcomes inside each section (like a DNS servfail). A payload therefore
    means the collector completed; a whole-collector crash is caught in the worker
    and produces a scan-level error instead."""
    return STATUS_OK, None


# ---------------------------------------------------------------------------
# Collector registry — dimension key -> how to collect, judge, and project it.
# Lets one scan carry several collectors' raw results (scan_results is keyed by
# UNIQUE(scan_id, collector)); the CLI selects the set (default: all).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CollectorSpec:
    dimension: str  # CLI key, e.g. "email"
    collector: str  # scan_results.collector value, e.g. "dns_email"
    collect: Callable[[str, dict[str, Any]], dict[str, Any]]
    status: Callable[[dict[str, Any]], tuple[str, str | None]]
    project: Callable[[dict[str, Any]], list[dict[str, Any]]] | None  # dns_records rows


# Collect is wrapped in a lambda so it resolves the module attribute at call time
# (keeps monkeypatching in tests working, like the legacy collect_fn default).
REGISTRY: dict[str, CollectorSpec] = {
    "email": CollectorSpec(
        "email",
        dns_email.COLLECTOR_NAME,
        lambda d, s: dns_email.collect(d, s),
        scan_status,
        dns_email.dns_records_from_payload,
    ),
    "transport": CollectorSpec(
        "transport",
        tls_http.COLLECTOR,
        lambda d, s: tls_http.collect(d, s),
        transport_status,
        None,
    ),
}
DEFAULT_COLLECTORS = ["email", "transport"]


def resolve_specs(dimensions: Iterable[str]) -> list[CollectorSpec]:
    """Map CLI dimension keys to specs, preserving order and rejecting unknowns."""
    specs: list[CollectorSpec] = []
    for name in dimensions:
        spec = REGISTRY.get(name)
        if spec is None:
            known = ", ".join(REGISTRY)
            raise ValueError(f"unknown collector/dimension {name!r} (known: {known})")
        specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# Persistence — the shared write contract for single and batch scans
# ---------------------------------------------------------------------------


def store_scan(
    conn,
    payload: dict[str, Any],
    *,
    status: str,
    error: str | None,
    run_label: str | None = None,
    source: str = "manual",
) -> int:
    """Persist one completed dns_email scan (raw payload + dns_records projection).

    The single source of truth for how a dimension-A scan is written, used by both
    ``karne scan`` and ``karne batch``. Never overwrites raw data (rule 5): every
    call is a new ``scans`` row and a new ``scan_results`` row.
    """
    domain = storage.get_or_create_domain(conn, payload["domain"], source=source)
    scan_id = storage.insert_scan(
        conn,
        Scan(
            domain_id=domain.id,
            scanner_version=__version__,
            config_hash=payload.get("config_hash"),
            run_label=run_label,
        ),
    )
    storage.insert_scan_result(
        conn,
        ScanResult(scan_id=scan_id, collector=dns_email.COLLECTOR_NAME, payload=payload),
    )
    storage.insert_dns_records(
        conn,
        [DnsRecord(scan_id=scan_id, **row) for row in dns_email.dns_records_from_payload(payload)],
    )
    storage.finish_scan(conn, scan_id, status=status, error=error)
    return scan_id


def store_error_scan(
    conn,
    domain_name: str,
    *,
    error: str,
    run_label: str | None = None,
    source: str = "manual",
) -> int:
    """Record a scan-level failure (the collector crashed) as an ``error`` row.

    No ``scan_results`` is written because there is no raw output to store; the
    failure lives on the ``scans`` row (rule 6: recorded as "could not measure",
    kept distinct from a normal no-record result). Re-scanned on the next run.
    """
    domain = storage.get_or_create_domain(
        conn, dns_email.normalize_domain(domain_name), source=source
    )
    scan_id = storage.insert_scan(
        conn,
        Scan(domain_id=domain.id, scanner_version=__version__, run_label=run_label),
    )
    storage.finish_scan(conn, scan_id, status=STATUS_ERROR, error=error)
    return scan_id


# ---------------------------------------------------------------------------
# Multi-collector bundle: one scan, several collectors' raw results
# ---------------------------------------------------------------------------


@dataclass
class CollectorOutcome:
    """Result of running one collector on one domain within a scan bundle."""

    spec: CollectorSpec
    payload: dict[str, Any] | None  # None only if the collector code crashed
    status: str
    error: str | None


def collect_bundle(
    domain: str, settings: dict[str, Any], specs: list[CollectorSpec]
) -> list[CollectorOutcome]:
    """Run each collector for one domain; a crash in one does not abort the others
    (rule 3). Runs in a worker thread — no DB access here."""
    outcomes: list[CollectorOutcome] = []
    for spec in specs:
        try:
            payload = spec.collect(domain, settings)
        except Exception as exc:  # whole-collector crash -> recorded, others continue
            outcomes.append(
                CollectorOutcome(spec, None, STATUS_ERROR, f"{type(exc).__name__}: {exc}")
            )
            continue
        status, error = spec.status(payload)
        outcomes.append(CollectorOutcome(spec, payload, status, error))
    return outcomes


def combine_status(outcomes: list[CollectorOutcome]) -> tuple[str, str | None]:
    """Scan-level status across collectors (matches models.py definitions):
    ok = all succeeded; error = all failed; partial = a mix (rule 6 preserved)."""
    any_ok = any(o.payload is not None and o.status == STATUS_OK for o in outcomes)
    any_bad = any(o.payload is None or o.status != STATUS_OK for o in outcomes)
    detail = "; ".join(f"{o.spec.collector}: {o.error}" for o in outcomes if o.error) or None
    if not any_bad:
        return STATUS_OK, None
    if not any_ok:
        return STATUS_ERROR, detail
    return STATUS_PARTIAL, detail


def store_bundle(
    conn,
    domain_name: str,
    outcomes: list[CollectorOutcome],
    *,
    run_label: str | None = None,
    source: str = "manual",
) -> tuple[int, str, str | None]:
    """Persist one scan carrying several collectors' results (rule 5: append-only).

    One ``scans`` row; one ``scan_results`` row per collector that produced a
    payload, plus that collector's projection (dns_records for dimension A). The
    scan-level status combines the collectors'. Collectors that crashed contribute
    to the status/error but write no ``scan_results`` (rule 6)."""
    status, error = combine_status(outcomes)
    dom_norm = next(
        (o.payload["domain"] for o in outcomes if o.payload and o.payload.get("domain")),
        dns_email.normalize_domain(domain_name),
    )
    config_hash = next((o.payload.get("config_hash") for o in outcomes if o.payload), None)
    domain = storage.get_or_create_domain(conn, dom_norm, source=source)
    scan_id = storage.insert_scan(
        conn,
        Scan(
            domain_id=domain.id,
            scanner_version=__version__,
            config_hash=config_hash,
            run_label=run_label,
        ),
    )
    for o in outcomes:
        if o.payload is None:
            continue
        storage.insert_scan_result(
            conn, ScanResult(scan_id=scan_id, collector=o.spec.collector, payload=o.payload)
        )
        if o.spec.project is not None:
            storage.insert_dns_records(
                conn,
                [DnsRecord(scan_id=scan_id, **row) for row in o.spec.project(o.payload)],
            )
    storage.finish_scan(conn, scan_id, status=status, error=error)
    return scan_id, status, error


# ---------------------------------------------------------------------------
# Progress / summary
# ---------------------------------------------------------------------------


@dataclass
class BatchProgress:
    """Live counters for one ``run_batch`` invocation."""

    to_scan: int  # domains selected to scan in this invocation
    already_done: int  # domains already completed in this run before we started
    scope_total: int  # total domains in scope (whole frame, or the sector)
    scanned: int = 0
    ok: int = 0
    partial: int = 0
    error: int = 0
    failures: list[str] = field(default_factory=list)  # "domain: error" (capped)

    def record(self, status: str) -> None:
        self.scanned += 1
        if status == STATUS_OK:
            self.ok += 1
        elif status == STATUS_PARTIAL:
            self.partial += 1
        else:
            self.error += 1

    @property
    def remaining(self) -> int:
        return self.to_scan - self.scanned

    def progress_line(self) -> str:
        return (
            f"[{self.scanned}/{self.to_scan}] "
            f"ok={self.ok} partial={self.partial} error={self.error} "
            f"remaining={self.remaining}"
        )

    def summary(self) -> str:
        done_after = self.already_done + self.ok + self.partial
        lines = [
            f"Run       : {done_after}/{self.scope_total} domains completed this round",
            f"This pass : scanned {self.scanned} "
            f"(ok={self.ok}, partial={self.partial}, error={self.error})",
            f"Skipped   : {self.already_done} already done before this pass",
        ]
        if self.failures:
            lines.append(f"Failures  : {len(self.failures)} (first {len(self.failures)} shown)")
            lines.extend(f"    {f}" for f in self.failures)
        return "\n".join(lines)


CollectFn = Callable[[str], dict[str, Any]]
ProgressCb = Callable[[BatchProgress], None]

_MAX_TRACKED_FAILURES = 20


def _scan_one(domain: str, collect_fn: CollectFn) -> tuple[dict[str, Any] | None, str, str | None]:
    """Run the collector for one domain in a worker thread; never raises.

    Returns ``(payload, status, error)``. ``payload`` is None only when the
    collector itself crashed (a scan-level error), in which case ``status`` is
    ``error`` and ``error`` carries the detail.
    """
    try:
        payload = collect_fn(domain)
    except Exception as exc:  # a whole-collector crash must not stop the run (rule 3)
        return None, STATUS_ERROR, f"{type(exc).__name__}: {exc}"
    status, error = scan_status(payload)
    return payload, status, error


def run_batch(
    conn,
    settings: dict[str, Any],
    *,
    run_label: str,
    sector: str | None = None,
    limit: int | None = None,
    collect_fn: CollectFn | None = None,
    concurrency: int | None = None,
    progress_cb: ProgressCb | None = None,
    progress_every: int = 50,
    source: str = "frame",
    collectors: list[str] | None = None,
) -> BatchProgress:
    """Scan the pending frame domains for ``run_label`` in parallel; persist each.

    Pure orchestration: ``concurrency`` and the domain selection are injectable/
    observable so the engine is unit-testable with no network.

    Two modes: pass ``collectors`` (dimension keys, e.g. ``["email", "transport"]``)
    to run a multi-collector bundle per domain (one scan, several ``scan_results``);
    otherwise the legacy single-collector path runs, using ``collect_fn`` (default:
    the real dns_email collector). Returns the final :class:`BatchProgress`.
    """
    use_multi = collectors is not None and collect_fn is None
    specs = resolve_specs(collectors) if use_multi else None
    if collect_fn is None and not use_multi:
        collect_fn = lambda d: dns_email.collect(d, settings)  # noqa: E731
    if concurrency is None:
        concurrency = int(settings.get("dns", {}).get("concurrency", 4))
    concurrency = max(1, concurrency)

    pending = storage.select_domains_to_scan(conn, run_label, sector=sector, limit=limit)
    progress = BatchProgress(
        to_scan=len(pending),
        already_done=storage.count_done_domains(conn, run_label, sector=sector),
        scope_total=storage.count_domains(conn, sector=sector),
    )
    if not pending:
        if progress_cb is not None:
            progress_cb(progress)
        return progress

    def _record(domain: str, status: str, error: str | None) -> None:
        progress.record(status)
        if status == STATUS_ERROR and len(progress.failures) < _MAX_TRACKED_FAILURES:
            progress.failures.append(f"{domain}: {error}")
        if progress_cb is not None and progress.scanned % progress_every == 0:
            progress_cb(progress)

    # Workers only do network I/O; all DB writes happen here on the main thread.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        if use_multi:
            futures = {pool.submit(collect_bundle, d.domain, settings, specs): d for d in pending}
            for future in as_completed(futures):
                d = futures[future]
                outcomes = future.result()
                _, status, error = store_bundle(
                    conn, d.domain, outcomes, run_label=run_label, source=source
                )
                _record(d.domain, status, error)
        else:
            futures = {pool.submit(_scan_one, d.domain, collect_fn): d for d in pending}
            for future in as_completed(futures):
                d = futures[future]
                payload, status, error = future.result()
                if payload is not None:
                    store_scan(
                        conn,
                        payload,
                        status=status,
                        error=error,
                        run_label=run_label,
                        source=source,
                    )
                else:
                    store_error_scan(
                        conn,
                        d.domain,
                        error=error or "collector error",
                        run_label=run_label,
                        source=source,
                    )
                _record(d.domain, status, error)

    if progress_cb is not None:
        progress_cb(progress)
    return progress


def domains_scanned_this_run(entries: Iterable[Domain]) -> list[str]:
    """Small pure helper: the domain names of a selection (used in tests/summaries)."""
    return [e.domain for e in entries]
