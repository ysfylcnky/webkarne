"""Offline unit tests for the batch scanning engine (Sprint 2).

No network: the collector is replaced by an injected ``collect_fn`` that returns
canned payloads. These tests exercise the orchestration only — domain selection /
resume, parallel execution under a concurrency cap, the ok/partial/error paths,
progress counting, and the shared write contract (raw payload + dns_records).
"""

from __future__ import annotations

import threading
import time

import pytest

from karne import batch, storage
from karne.collectors.dns_email import _RateLimiter
from karne.models import Domain

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    connection = storage.connect(tmp_path / "karne.db")
    storage.init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def _seed(conn, domains: list[tuple[str, str | None]]) -> None:
    """Insert frame domains as (domain, sector)."""
    storage.add_domains(conn, [Domain(domain=d, source="frame", sector=s) for d, s in domains])


def fake_payload(domain: str, *, indicator_error: bool = False) -> dict:
    """A minimal but structurally valid dns_email payload for one domain."""
    payload = {
        "collector": "dns_email",
        "collector_version": "test",
        "input_domain": domain,
        "domain": domain.lower(),
        "collected_at": "2026-11-01T00:00:00+00:00",
        "resolvers": ["1.1.1.1", "8.8.8.8"],
        "config_hash": "testhash",
        "spf": {},
        "dmarc": {},
        "dkim": {},
        "mx": {},
        "dane": {},
        "mta_sts": {},
        "tls_rpt": {},
        "dnssec": {},
        "caa": {},
        "queries": [],
    }
    if indicator_error:
        payload["spf"] = {"error": "collector bug"}
    return payload


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_default_run_label_is_year_month():
    from datetime import UTC, datetime

    label = batch.default_run_label(datetime(2026, 11, 3, 12, 0, tzinfo=UTC))
    assert label == "2026-11"


def test_scan_status_ok_and_partial():
    assert batch.scan_status(fake_payload("x.com")) == ("ok", None)
    status, detail = batch.scan_status(fake_payload("x.com", indicator_error=True))
    assert status == "partial"
    assert "spf" in detail


# ---------------------------------------------------------------------------
# Domain selection / resume
# ---------------------------------------------------------------------------


def test_select_skips_done_domains_in_same_run(conn):
    _seed(conn, [("a.tr", None), ("b.tr", None), ("c.tr", None)])
    label = "2026-11"
    # Scan a.tr and b.tr in this round.
    batch.store_scan(conn, fake_payload("a.tr"), status="ok", error=None, run_label=label)
    batch.store_scan(conn, fake_payload("b.tr"), status="partial", error="x", run_label=label)

    pending = storage.select_domains_to_scan(conn, label)
    assert [d.domain for d in pending] == ["c.tr"]  # a/b done, c remains


def test_error_status_is_not_treated_as_done(conn):
    _seed(conn, [("a.tr", None)])
    label = "2026-11"
    batch.store_error_scan(conn, "a.tr", error="boom", run_label=label)
    pending = storage.select_domains_to_scan(conn, label)
    assert [d.domain for d in pending] == ["a.tr"]  # error -> re-scanned


def test_selection_is_per_run_label(conn):
    _seed(conn, [("a.tr", None)])
    batch.store_scan(conn, fake_payload("a.tr"), status="ok", error=None, run_label="2026-10")
    # A different round has not scanned it yet.
    pending = storage.select_domains_to_scan(conn, "2026-11")
    assert [d.domain for d in pending] == ["a.tr"]


def test_sector_and_limit_filters(conn):
    _seed(conn, [("bank1.tr", "bank"), ("bank2.tr", "bank"), ("uni.tr", "university")])
    banks = storage.select_domains_to_scan(conn, "2026-11", sector="bank")
    assert {d.domain for d in banks} == {"bank1.tr", "bank2.tr"}
    capped = storage.select_domains_to_scan(conn, "2026-11", limit=1)
    assert len(capped) == 1


# ---------------------------------------------------------------------------
# run_batch end-to-end (fake collector)
# ---------------------------------------------------------------------------


def test_run_batch_scans_all_and_writes_raw(conn):
    _seed(conn, [("a.tr", None), ("b.tr", None)])
    progress = batch.run_batch(
        conn, {}, run_label="2026-11", collect_fn=fake_payload, concurrency=2
    )
    assert (progress.scanned, progress.ok, progress.error) == (2, 2, 0)

    # Each domain has a finished scan with raw scan_results + a dns_records projection.
    for domain in ("a.tr", "b.tr"):
        scan = storage.latest_scan_for_domain(conn, domain)
        assert scan.status == "ok"
        assert scan.run_label == "2026-11"
        assert scan.finished_at is not None
        result = storage.get_scan_result(conn, scan.id, "dns_email")
        assert result is not None and result.payload["domain"] == domain
        assert storage.get_dns_records(conn, scan.id)  # projection written


def test_run_batch_resumes(conn):
    _seed(conn, [("a.tr", None), ("b.tr", None)])
    batch.run_batch(conn, {}, run_label="2026-11", collect_fn=fake_payload, concurrency=2)
    # Second pass: everything already done -> nothing scanned.
    again = batch.run_batch(conn, {}, run_label="2026-11", collect_fn=fake_payload)
    assert again.to_scan == 0
    assert again.scanned == 0
    assert again.already_done == 2


def test_run_batch_records_partial(conn):
    _seed(conn, [("a.tr", None)])

    def collect(domain):
        return fake_payload(domain, indicator_error=True)

    progress = batch.run_batch(conn, {}, run_label="2026-11", collect_fn=collect)
    assert progress.partial == 1 and progress.ok == 0
    scan = storage.latest_scan_for_domain(conn, "a.tr")
    assert scan.status == "partial"
    assert storage.get_scan_result(conn, scan.id, "dns_email") is not None  # raw still stored


def test_run_batch_survives_collector_crash(conn):
    _seed(conn, [("good.tr", None), ("bad.tr", None)])

    def collect(domain):
        if domain == "bad.tr":
            raise RuntimeError("collector exploded")
        return fake_payload(domain)

    progress = batch.run_batch(conn, {}, run_label="2026-11", collect_fn=collect, concurrency=2)
    assert progress.ok == 1 and progress.error == 1  # run did not stop
    bad = storage.latest_scan_for_domain(conn, "bad.tr")
    assert bad.status == "error"
    assert "RuntimeError" in bad.error
    # A crashed collector writes no raw scan_result (there was no output).
    assert storage.get_scan_result(conn, bad.id, "dns_email") is None
    assert any("bad.tr" in f for f in progress.failures)


def test_run_batch_respects_limit(conn):
    _seed(conn, [("a.tr", None), ("b.tr", None), ("c.tr", None)])
    progress = batch.run_batch(conn, {}, run_label="2026-11", collect_fn=fake_payload, limit=2)
    assert progress.to_scan == 2 and progress.scanned == 2
    # One domain remains pending.
    assert len(storage.select_domains_to_scan(conn, "2026-11")) == 1


def test_run_batch_never_overwrites_prior_round(conn):
    _seed(conn, [("a.tr", None)])
    batch.run_batch(conn, {}, run_label="2026-10", collect_fn=fake_payload)
    batch.run_batch(conn, {}, run_label="2026-11", collect_fn=fake_payload)
    # Two distinct scans exist for the same domain (rule 5: raw never overwritten).
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM scans s JOIN domains d ON d.id = s.domain_id "
        "WHERE d.domain = 'a.tr';"
    ).fetchone()
    assert rows["n"] == 2


# ---------------------------------------------------------------------------
# Concurrency is actually bounded by the configured limit
# ---------------------------------------------------------------------------


def test_concurrency_is_capped(conn):
    _seed(conn, [(f"d{i}.tr", None) for i in range(12)])
    lock = threading.Lock()
    state = {"active": 0, "max": 0}

    def collect(domain):
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.02)  # hold the worker so overlap is observable
        with lock:
            state["active"] -= 1
        return fake_payload(domain)

    batch.run_batch(conn, {}, run_label="2026-11", collect_fn=collect, concurrency=3)
    assert state["max"] <= 3  # never more than the configured parallelism
    assert state["max"] >= 2  # and it did run in parallel


def test_concurrency_defaults_from_settings(conn):
    _seed(conn, [("a.tr", None)])
    settings = {"dns": {"concurrency": 1}}
    # Just assert it runs and reads the setting without error (no override passed).
    progress = batch.run_batch(conn, settings, run_label="2026-11", collect_fn=fake_payload)
    assert progress.scanned == 1


# ---------------------------------------------------------------------------
# Rate limiter math (deterministic, fake clock) — gentleness is enforced
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.t += seconds


def test_rate_limiter_spaces_out_acquires(monkeypatch):
    from karne.collectors import dns_email as de

    clock = _FakeClock()
    monkeypatch.setattr(de.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(de.time, "sleep", clock.sleep)

    limiter = _RateLimiter(rate_per_second=100.0)  # interval = 0.01s
    for _ in range(5):
        limiter.acquire()
    # First acquire is free; the next four are each spaced by one interval.
    assert clock.slept == pytest.approx(0.04, abs=1e-9)


def test_rate_limiter_zero_is_unlimited(monkeypatch):
    from karne.collectors import dns_email as de

    clock = _FakeClock()
    monkeypatch.setattr(de.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(de.time, "sleep", clock.sleep)

    limiter = _RateLimiter(rate_per_second=0)
    for _ in range(5):
        limiter.acquire()
    assert clock.slept == 0.0


# ---------------------------------------------------------------------------
# Multi-collector bundle (Sprint 3 — dimension B wiring)
# ---------------------------------------------------------------------------


def fake_b_payload(domain: str) -> dict:
    """Minimal structurally valid tls_http payload."""
    return {
        "collector": "tls_http",
        "collector_version": "test",
        "input_domain": domain,
        "domain": domain.lower(),
        "collected_at": "2026-11-01T00:00:00+00:00",
        "config_hash": "testhash",
        "http": {"hops": 1, "reached_https": True, "cleartext_after_https": False},
        "tls_versions": {"probed": {}, "supported": ["TLSv1.3"], "note": ""},
        "certificate": {"obtained": True, "verified": True},
        "homepage": {
            "reachable": True,
            "status": 200,
            "security_headers": {},
            "hsts": {"present": False},
        },
        "security_txt": {"present": False},
    }


def test_resolve_specs_rejects_unknown():
    with pytest.raises(ValueError, match="unknown collector"):
        batch.resolve_specs(["email", "bogus"])
    specs = batch.resolve_specs(["transport", "email"])
    assert [s.dimension for s in specs] == ["transport", "email"]  # order preserved


def test_combine_status_rules():
    email = batch.REGISTRY["email"]
    transport = batch.REGISTRY["transport"]
    ok = [
        batch.CollectorOutcome(email, {}, "ok", None),
        batch.CollectorOutcome(transport, {}, "ok", None),
    ]
    mixed = [
        batch.CollectorOutcome(email, {}, "ok", None),
        batch.CollectorOutcome(transport, None, "error", "boom"),
    ]
    allbad = [
        batch.CollectorOutcome(email, None, "error", "x"),
        batch.CollectorOutcome(transport, None, "error", "y"),
    ]
    assert batch.combine_status(ok)[0] == "ok"
    assert batch.combine_status(mixed)[0] == "partial"
    assert batch.combine_status(allbad)[0] == "error"


def test_collect_bundle_isolates_a_crash():
    good = batch.CollectorSpec(
        "email", "dns_email", lambda d, s: fake_payload(d), batch.scan_status, None
    )
    bad = batch.CollectorSpec(
        "transport",
        "tls_http",
        lambda d, s: (_ for _ in ()).throw(RuntimeError("boom")),
        batch.transport_status,
        None,
    )
    outcomes = batch.collect_bundle("a.tr", {}, [good, bad])
    assert outcomes[0].payload is not None and outcomes[0].status == "ok"
    assert outcomes[1].payload is None and outcomes[1].status == "error"
    assert "boom" in outcomes[1].error


def test_store_bundle_writes_one_scan_two_results(conn):
    email = batch.REGISTRY["email"]  # has a dns_records projection
    transport = batch.REGISTRY["transport"]  # no projection
    outcomes = [
        batch.CollectorOutcome(email, fake_payload("a.tr"), "ok", None),
        batch.CollectorOutcome(transport, fake_b_payload("a.tr"), "ok", None),
    ]
    scan_id, status, error = batch.store_bundle(conn, "a.tr", outcomes, run_label="2026-11")
    assert status == "ok" and error is None
    assert storage.get_scan_result(conn, scan_id, "dns_email") is not None
    assert storage.get_scan_result(conn, scan_id, "tls_http") is not None
    # exactly one scan row for the domain
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1


def test_store_bundle_partial_writes_only_successful(conn):
    email = batch.REGISTRY["email"]
    transport = batch.REGISTRY["transport"]
    outcomes = [
        batch.CollectorOutcome(email, fake_payload("a.tr"), "ok", None),
        batch.CollectorOutcome(transport, None, "error", "connect failed"),
    ]
    scan_id, status, error = batch.store_bundle(conn, "a.tr", outcomes, run_label="2026-11")
    assert status == "partial"
    assert "connect failed" in error
    assert storage.get_scan_result(conn, scan_id, "dns_email") is not None
    assert storage.get_scan_result(conn, scan_id, "tls_http") is None  # crashed -> no raw row
