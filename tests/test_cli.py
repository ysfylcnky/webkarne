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
    assert "Domain" in text and "SPF" in text and "DMARC" in text
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
