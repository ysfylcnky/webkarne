"""Live-network integration tests for the TLS/HTTP collector (dimension B).

DESELECTED by default (they make real HTTPS connections). Run explicitly with::

    uv run pytest -m network

They assert structure and invariants, not specific values (certs rotate, headers
change), so they stay stable as the outside world changes. Passive and
browser-equivalent (PLAN.md K-07): homepage GET + TLS handshakes on 443 only.
"""

from __future__ import annotations

import pytest

from karne.collectors import tls_http

pytestmark = pytest.mark.network


def test_collect_returns_full_structure():
    payload = tls_http.collect("internet.nl")
    for key in ("http", "tls_versions", "certificate", "homepage", "security_txt"):
        assert key in payload, key
    assert payload["collector"] == "tls_http"

    # A well-run reference site: reaches https, a modern TLS version is supported,
    # and its certificate verifies. (internet.nl practises what it preaches.)
    assert payload["http"]["reached_https"] is True
    assert "TLSv1.3" in payload["tls_versions"]["supported"]
    assert payload["certificate"]["verified"] is True
    assert payload["certificate"]["days_remaining"] is not None


def test_tls_version_probe_states_are_valid():
    payload = tls_http.collect("internet.nl")
    valid = {"supported", "not_supported", "unprobeable_local", "error"}
    for name, result in payload["tls_versions"]["probed"].items():
        assert result["status"] in valid, (name, result)
