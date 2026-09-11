"""Live-network integration tests for the DNS/email collector.

These require real DNS (and one HTTPS GET) and are DESELECTED by default. Run
them explicitly with::

    uv run pytest -m network

They assert structure and invariants, not specific record values (which change
over time), so they stay stable as the outside world changes.
"""

from __future__ import annotations

import pytest

from karne.collectors import dns_email as de

pytestmark = pytest.mark.network

_VALID_STATUSES = {"ok", "nxdomain", "noanswer", "timeout", "servfail", "error"}


def test_collect_returns_full_structure():
    payload = de.collect("google.com")
    for key in (
        "spf",
        "dmarc",
        "dkim",
        "mx",
        "dane",
        "mta_sts",
        "tls_rpt",
        "dnssec",
        "caa",
        "queries",
    ):
        assert key in payload
    assert payload["domain"] == "google.com"
    assert payload["queries"], "expected at least one logged query"
    for query in payload["queries"]:
        assert query["status"] in _VALID_STATUSES


def test_collect_google_has_spf_and_mx():
    payload = de.collect("google.com")
    assert payload["spf"]["present"] is True
    assert payload["mx"]["present"] is True
    # Google publishes DMARC; policy value is not asserted (it may change).
    assert payload["dmarc"]["present"] is True


def test_collect_never_raises_on_bogus_domain():
    # A non-existent domain must produce a recorded result, not an exception.
    payload = de.collect("this-domain-should-not-exist-karne-test.example")
    assert payload["spf"]["present"] is False
    assert payload["mx"]["present"] is False
