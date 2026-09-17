"""Live-browser integration tests for the privacy collector (dimension C).

DESELECTED by default (a real Chromium visits real sites). Run explicitly with::

    uv sync --group privacy && uv run playwright install chromium
    uv run pytest -m network tests/test_web_privacy_network.py

The expected results below were HAND-WRITTEN BEFORE the collector existed
(CLAUDE.md "expected output before code"), from sources independent of the
collector: our own templates and CSP for webkarne.com, and the raw homepage HTML of
mumifashion.com fetched with curl on 2026-09-17. If one fails, investigate the
measurement first; do not edit the expectation to match the code.

Only the "untouched" state exists in Sprint 4 · Session 1 (PLAN.md K-06/K-16).
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

from karne.collectors import web_privacy  # noqa: E402

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def webkarne() -> dict:
    return web_privacy.collect("webkarne.com")


@pytest.fixture(scope="module")
def mumifashion() -> dict:
    return web_privacy.collect("mumifashion.com")


def _hosts(state: dict) -> set[str]:
    return {r["host"] for r in state["requests"] if r["host"]}


def test_payload_carries_three_states_only_untouched_run(webkarne):
    assert set(webkarne["states"]) == {"untouched", "rejected", "accepted"}
    assert webkarne["states"]["rejected"]["outcome"] == "not_run"
    assert webkarne["states"]["accepted"]["outcome"] == "not_run"
    assert "WebKarne/1.0 (+https://webkarne.com/tr/hakkinda" in webkarne["browser"]["user_agent"]


def test_webkarne_untouched_expected(webkarne):
    """Our own site: no cookies, no storage, only Google Fonts as third parties.

    Source: karne/web/templates (only /static assets + Google Fonts CSS), CSP in
    deploy/Caddyfile (style-src fonts.googleapis.com, font-src fonts.gstatic.com), no
    Set-Cookie from the app, no localStorage/sessionStorage use in app.js. The apex
    redirects 307 to /tr/.

    Correction after the first live run (2026-09-17), with evidence: Cloudflare Web
    Analytics injects a beacon <script> from static.cloudflareinsights.com at the
    edge, but only for browser-like requests (Accept: text/html; the curl used for the
    original expectation sent */* and did not receive it). Our CSP script-src 'self'
    blocks it, so the browser attempts it but it never leaves: failure == "csp".
    """
    s = webkarne["states"]["untouched"]
    assert s["outcome"] == "loaded", s.get("error")
    assert s["page"]["final_url"] == "https://webkarne.com/tr/"
    assert s["page"]["main_status"] == 200
    assert {"url": "https://webkarne.com/", "status": 307} in s["page"]["redirects"]
    assert s["page"]["interactions"] == []
    assert s["cookies"] == []
    assert s["storage"]["local_storage_keys"] == []
    assert s["storage"]["session_storage_keys"] == []

    sent = {r["host"] for r in s["requests"] if r["failure"] is None}
    assert sent == {"webkarne.com", "fonts.googleapis.com", "fonts.gstatic.com"}
    beacon = [r for r in s["requests"] if r["host"] == "static.cloudflareinsights.com"]
    assert beacon and all(r["failure"] == "csp" for r in beacon)
    assert _hosts(s) == sent | {"static.cloudflareinsights.com"}


def test_mumifashion_untouched_expected(mumifashion):
    """WooCommerce shop. Source: its homepage HTML (2026-09-17).

    - Google Fonts stylesheets (Blocksy + Elementor) -> fonts.googleapis.com/gstatic.
    - WooCommerce scripts under /wp-content/plugins/woocommerce/.
    - WooCommerce order attribution (sourcebuster, allowTracking=true) writes the
      sbjs_* cookies from JavaScript -> not HttpOnly.
    - No tag manager, Meta Pixel or TikTok pixel in the HTML ("tiktok" is only a
      social link), so no requests to those hosts.
    """
    s = mumifashion["states"]["untouched"]
    assert s["outcome"] == "loaded", s.get("error")
    assert s["page"]["final_host"] == "mumifashion.com"
    assert s["page"]["main_status"] == 200
    assert s["page"]["interactions"] == []

    hosts = _hosts(s)
    assert {"mumifashion.com", "fonts.googleapis.com", "fonts.gstatic.com"} <= hosts
    assert any(
        r["host"] == "mumifashion.com"
        and r["resource_type"] == "script"
        and "/wp-content/plugins/woocommerce/" in r["url"]
        for r in s["requests"]
    )

    cookies = {c["name"]: c for c in s["cookies"]}
    for name in ("sbjs_current", "sbjs_first", "sbjs_session"):
        assert name in cookies, sorted(cookies)
        assert cookies[name]["http_only"] is False

    for host in ("www.googletagmanager.com", "connect.facebook.net", "analytics.tiktok.com"):
        assert host not in hosts


def test_no_values_are_stored(mumifashion):
    """Cookie and storage VALUES are never recorded (PLAN.md K-16, §4)."""
    s = mumifashion["states"]["untouched"]
    assert all("value" not in c for c in s["cookies"])
    assert set(s["storage"]) == {
        "origin",
        "local_storage_keys",
        "session_storage_keys",
        "indexeddb_names",
        "error",
    }


def test_unresolvable_domain_is_dns_error_not_empty():
    """Rule 6: a name that does not resolve is 'could not measure', never 'no cookies'."""
    payload = web_privacy.collect("does-not-exist-karne-test.invalid")
    s = payload["states"]["untouched"]
    assert s["outcome"] == "dns_error"
    assert s["error"] and "ERR_NAME_NOT_RESOLVED" in s["error"]["message"]
