"""Offline tests for the CLI: scan-status logic, the dns_records projection,
summary formatting, and the store/--json/--no-store paths.

The network-bound collector is monkeypatched with a canned payload, so these
tests run without DNS access.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from karne import cli, storage
from karne.collectors.dns_email import dns_records_from_payload

runner = CliRunner()


def sample_payload() -> dict:
    return {
        "collector": "dns_email",
        "collector_version": "0.1.0",
        "input_domain": "Example.COM",
        "domain": "example.com",
        "collected_at": "2026-01-01T00:00:00+00:00",
        "resolvers": ["203.0.113.53"],
        "config_hash": "abc123",
        "spf": {
            "query": {"status": "ok"},
            "records": ["v=spf1 -all"],
            "present": True,
            "multiple": False,
            "parsed": {"version_ok": True, "terminator": {"raw": "-all"}},
            "lookups": {
                "total_lookups": 0,
                "exceeds_limit": False,
                "limit": 10,
                "loop_detected": False,
            },
        },
        "dmarc": {
            "query": {"status": "ok"},
            "records": ["v=DMARC1; p=reject"],
            "present": True,
            "multiple": False,
            "parsed": {
                "valid": True,
                "p": "reject",
                "has_aggregate_reporting": False,
                "issues": [],
            },
        },
        "dkim": {
            "method": "selector_guessing",
            "selectors_tried": ["mail", "google"],
            "attempts": [
                {
                    "selector": "mail",
                    "query": {"status": "ok", "answers": ["v=DKIM1; k=rsa; p=AAAA"]},
                    "present": True,
                    "parsed": {"key_type": "rsa", "key_bits": 2048, "p_empty": False},
                },
                {
                    "selector": "google",
                    "query": {"status": "nxdomain", "answers": []},
                    "present": False,
                },
            ],
            "found_selectors": ["mail"],
        },
        "mx": {
            "query": {"status": "ok"},
            "present": True,
            "records": [{"preference": 10, "exchange": "mail.example.com.", "provider": "local"}],
            "providers": ["local"],
        },
        "dane": {
            "mx_hosts_checked": ["mail.example.com"],
            "hosts": [
                {
                    "mx_host": "mail.example.com",
                    "query": {"status": "ok"},
                    "present": True,
                    "records": [
                        {"usage": 3, "selector": 1, "matching_type": 1, "raw": "3 1 1 abcd"}
                    ],
                }
            ],
            "present": True,
        },
        "mta_sts": {
            "dns": {"query": {"status": "nxdomain"}, "records": [], "present": False},
            "policy": {"status": "error"},
        },
        "tls_rpt": {"query": {"status": "noanswer"}, "records": [], "present": False},
        "dnssec": {"query": {"status": "ok"}, "ds_present": True, "resolver_authenticated": False},
        "caa": {"query": {"status": "noanswer"}, "present": False, "records": []},
        "queries": [{"name": "example.com", "rtype": "TXT", "status": "ok"}],
    }


# ---------------------------------------------------------------------------
# Projection & status logic
# ---------------------------------------------------------------------------


def test_dns_records_projection():
    records = dns_records_from_payload(sample_payload())
    by_type: dict[str, list[dict]] = {}
    for r in records:
        by_type.setdefault(r["rtype"], []).append(r)

    assert by_type["SPF"][0]["valid"] is True
    assert "lookups=0" in by_type["SPF"][0]["notes"]
    assert by_type["DMARC"][0]["notes"] == "p=reject"
    dkim = by_type["DKIM"][0]
    assert dkim["selector"] == "mail" and "key_bits=2048" in dkim["notes"]
    assert by_type["MX"][0]["notes"] == "provider=local"
    assert by_type["TLSA"][0]["value"] == "3 1 1 abcd"
    assert "mx_host=mail.example.com" in by_type["TLSA"][0]["notes"]
    assert "status=nxdomain" in by_type["MTA-STS"][0]["notes"]
    assert by_type["DS"][0]["value"] == "present"


def test_scan_status_ok():
    status, error = cli._scan_status(sample_payload())
    assert status == "ok"
    assert error is None


def test_scan_status_partial_on_indicator_error():
    payload = sample_payload()
    payload["spf"] = {"error": "RuntimeError: boom"}
    status, error = cli._scan_status(payload)
    assert status == "partial"
    assert "spf" in error


def test_format_summary_smoke():
    text = cli.format_summary(sample_payload(), stored=True, scan_id=7, status="ok")
    assert "Domain" in text and "SPF" in text and "DMARC" in text and "DANE" in text
    assert "scan #7" in text


def test_format_summary_handles_servfail():
    payload = sample_payload()
    payload["dmarc"] = {"query": {"status": "servfail"}, "records": [], "present": False}
    text = cli.format_summary(payload, stored=False, scan_id=None, status="ok")
    # A failed query is shown as such, never as a definitive "no record".
    assert "servfail" in text


# ---------------------------------------------------------------------------
# CLI command (collector monkeypatched; no network)
# ---------------------------------------------------------------------------


def _patch_collect(monkeypatch):
    monkeypatch.setattr(cli.dns_email, "load_settings", lambda *a, **k: {})
    monkeypatch.setattr(cli.dns_email, "collect", lambda domain, settings: sample_payload())


def test_scan_stores_result(monkeypatch, tmp_path):
    _patch_collect(monkeypatch)
    db_path = tmp_path / "karne.db"
    result = runner.invoke(cli.app, ["scan", "example.com", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "scan #1" in result.output

    conn = storage.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1
    stored = storage.get_scan_result(conn, 1, "dns_email")
    assert stored.payload["domain"] == "example.com"  # raw payload persisted intact
    conn.close()


def test_scan_no_store(monkeypatch, tmp_path):
    _patch_collect(monkeypatch)
    db_path = tmp_path / "karne.db"
    result = runner.invoke(cli.app, ["scan", "example.com", "--no-store", "--db", str(db_path)])
    assert result.exit_code == 0
    assert "no (--no-store)" in result.output
    assert not db_path.exists()  # nothing was written


def test_scan_json_output(monkeypatch):
    _patch_collect(monkeypatch)
    result = runner.invoke(cli.app, ["scan", "example.com", "--json", "--no-store"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["domain"] == "example.com"
    assert "queries" in parsed


# ---------------------------------------------------------------------------
# frontier command (Sprint 1) — offline, using a fixture CSV (no download)
# ---------------------------------------------------------------------------

MINI_TRANCO = (
    "1,trendyol.com\n"       # curated ecommerce, also in Tranco
    "2,google.com\n"         # non-Turkish -> excluded
    "3,itu.edu.tr\n"         # university via TLD rule
    "4,garantibbva.com.tr\n" # bank via seed
    "5,randomcompany.com.tr\n"  # unknown .tr
)


def _write_mini(tmp_path):
    path = tmp_path / "mini.csv"
    path.write_text(MINI_TRANCO, encoding="utf-8")
    return path


def test_frontier_builds_and_stores(tmp_path):
    csv_path = _write_mini(tmp_path)
    db_path = tmp_path / "karne.db"
    result = runner.invoke(
        cli.app,
        ["frontier", "--tranco-file", str(csv_path), "--db", str(db_path),
         "--manifest-dir", str(tmp_path / "manifests")],
    )
    assert result.exit_code == 0, result.output
    assert "added" in result.output

    conn = storage.connect(db_path)
    # The three .tr rows plus the curated set are stored; google.com is excluded.
    assert storage.get_domain(conn, "itu.edu.tr").sector == "university"
    assert storage.get_domain(conn, "garantibbva.com.tr").sector == "bank"
    assert storage.get_domain(conn, "mumifashion.com").source == "curated_tr_com"
    assert storage.get_domain(conn, "google.com") is None
    conn.close()

    # A manifest JSON was written (reproducibility metadata).
    manifests = list((tmp_path / "manifests").glob("frame_*.json"))
    assert len(manifests) == 1
    man = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert man["frontier_version"] and man["total_domains"] >= 3


def test_frontier_no_store(tmp_path):
    csv_path = _write_mini(tmp_path)
    db_path = tmp_path / "karne.db"
    result = runner.invoke(
        cli.app,
        ["frontier", "--tranco-file", str(csv_path), "--no-store", "--db", str(db_path),
         "--manifest-dir", str(tmp_path / "manifests")],
    )
    assert result.exit_code == 0
    assert "no (--no-store)" in result.output
    assert not db_path.exists()  # nothing written to the DB
    # Manifest is still produced even without storing.
    assert list((tmp_path / "manifests").glob("frame_*.json"))


def test_frontier_requires_a_source(tmp_path):
    result = runner.invoke(cli.app, ["frontier", "--db", str(tmp_path / "k.db")])
    assert result.exit_code != 0
    assert "tranco-file" in result.output or "list-id" in result.output


# ---------------------------------------------------------------------------
# batch command (Sprint 2) — offline, collector monkeypatched
# ---------------------------------------------------------------------------

from karne.models import Domain  # noqa: E402


def _seed_domains(db_path, domains):
    conn = storage.connect(db_path)
    storage.init_db(conn)
    storage.add_domains(conn, [Domain(domain=d, source="frame") for d in domains])
    conn.close()


def test_batch_runs_and_stores(monkeypatch, tmp_path):
    db_path = tmp_path / "karne.db"
    _seed_domains(db_path, ["a.tr", "b.tr"])
    monkeypatch.setattr(cli.dns_email, "load_settings", lambda *a, **k: {})
    # Per-domain canned payload (the real collector is not called).
    monkeypatch.setattr(
        cli.dns_email,
        "collect",
        lambda domain, settings: {**sample_payload(), "domain": domain, "input_domain": domain},
    )
    result = runner.invoke(
        cli.app,
        ["batch", "--run-label", "2026-11", "--db", str(db_path), "--concurrency", "1"],
    )
    assert result.exit_code == 0, result.output
    assert "ok=2" in result.output

    conn = storage.connect(db_path)
    for domain in ("a.tr", "b.tr"):
        scan = storage.latest_scan_for_domain(conn, domain)
        assert scan.status == "ok" and scan.run_label == "2026-11"
    conn.close()


def test_batch_dry_run_writes_nothing(monkeypatch, tmp_path):
    db_path = tmp_path / "karne.db"
    _seed_domains(db_path, ["a.tr", "b.tr"])
    monkeypatch.setattr(cli.dns_email, "load_settings", lambda *a, **k: {})
    # collect must never be called in a dry run.
    monkeypatch.setattr(
        cli.dns_email,
        "collect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("collect must not run on --dry-run")),
    )
    result = runner.invoke(
        cli.app, ["batch", "--dry-run", "--run-label", "2026-11", "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing scanned." in result.output
    assert "2 to scan this pass" in result.output

    conn = storage.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0  # nothing written
    conn.close()


# ---------------------------------------------------------------------------
# rescore command (Sprint 3) — offline, collector monkeypatched
# ---------------------------------------------------------------------------


def _store_one_scan(monkeypatch, db_path):
    """Store a single ad-hoc scan via the scan command; returns nothing."""
    _patch_collect(monkeypatch)
    runner.invoke(cli.app, ["scan", "example.com", "--db", str(db_path)])


def test_rescore_scores_unscored_scans(monkeypatch, tmp_path):
    db_path = tmp_path / "karne.db"
    _store_one_scan(monkeypatch, db_path)

    result = runner.invoke(cli.app, ["rescore", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "1 scan(s) selected" in result.output
    assert "1/1 scored" in result.output

    conn = storage.connect(db_path)
    try:
        scan = storage.latest_scan_for_domain(conn, "example.com")
        scores = storage.get_scores(conn, scan.id)
        assert len(scores) == 1
        assert scores[0].dimension == "email"
        assert scores[0].ruleset_version  # a version was stamped
    finally:
        conn.close()


def test_rescore_dry_run_writes_nothing(monkeypatch, tmp_path):
    db_path = tmp_path / "karne.db"
    _store_one_scan(monkeypatch, db_path)

    result = runner.invoke(cli.app, ["rescore", "--db", str(db_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run: nothing written." in result.output

    conn = storage.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0
    finally:
        conn.close()


def test_rescore_rejects_unknown_dimension(tmp_path):
    db_path = tmp_path / "karne.db"
    result = runner.invoke(
        cli.app, ["rescore", "--dimension", "transport", "--db", str(db_path)]
    )
    assert result.exit_code == 2
    assert "Only 'email'" in result.output
