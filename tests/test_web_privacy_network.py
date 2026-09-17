"""Live-browser integration tests for the privacy collector (dimension C).

DESELECTED by default (a real Chromium visits real sites). Run explicitly with::

    uv sync --group privacy && uv run playwright install chromium
    uv run pytest -m network tests/test_web_privacy_network.py

The expected results below were HAND-WRITTEN BEFORE the collector existed
(CLAUDE.md "expected output before code"), from sources independent of the
collector: our own templates and CSP for webkarne.com, and the raw homepage HTML of
mumifashion.com fetched with curl on 2026-09-17. If one fails, investigate the
measurement first; do not edit the expectation to match the code.

Session 1 implemented "untouched"; Session 2 added the consent-UI observation and the
"rejected" state (PLAN.md K-06, K-16 addendum). Session 2's expectations (vodafone,
yapikredi, akbank) were written before its code from the in-app browser pane (DOM
inspection + screenshots, no clicks) on 2026-09-17.
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


def test_payload_carries_three_states(webkarne):
    assert set(webkarne["states"]) == {"untouched", "rejected", "accepted"}
    assert webkarne["states"]["rejected"]["outcome"] == "loaded"
    assert webkarne["states"]["accepted"]["outcome"] == "not_run"
    assert webkarne["browser"]["headless"] is False  # K-16 addendum
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


# ---------------------------------------------------------------------------
# Session 2: consent-UI observation + the "rejected" state
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vodafone() -> dict:
    return web_privacy.collect("vodafone.com.tr")


@pytest.fixture(scope="module")
def yapikredi() -> dict:
    return web_privacy.collect("yapikredi.com.tr")


@pytest.fixture(scope="module")
def akbank() -> dict:
    return web_privacy.collect("akbank.com")


def _control(ui: dict, text: str) -> dict:
    matches = [c for c in ui["controls"] if c["text"] == text and c["visible"]]
    assert matches, [(c["text"], c["visible"]) for c in ui["controls"]]
    return matches[0]


def _cookie_names(state: dict) -> set[str]:
    return {c["name"] for c in state["cookies"]}


def _assert_rejected_and_reloaded(state: dict, reject_text: str) -> None:
    assert state["outcome"] == "loaded", state.get("error")
    action = state["consent_action"]
    assert action["result"] == "clicked", action
    assert action["control"]["text"] == reject_text
    assert action["control"]["matched_role"] == "reject"
    assert len(state["page"]["interactions"]) == 1
    assert state["reload"]["performed"] is True
    assert state["reload"]["status"] == 200
    assert [s["phase"] for s in state["snapshots"]] == [
        "before_action",
        "after_action",
        "after_reload",
    ]
    phases = {r["phase"] for r in state["requests"]}
    assert {"before_action", "after_action", "after_reload"} <= phases
    # The rejection is remembered: no visible banner after the reload.
    assert state["consent_ui_after_reload"]["banner"]["found"] is False


def test_webkarne_has_no_banner(webkarne):
    """Our own site shows no consent banner, so nothing is clicked or reloaded."""
    for name in ("untouched", "rejected"):
        assert webkarne["states"][name]["consent_ui"]["banner"]["found"] is False
    rejected = webkarne["states"]["rejected"]
    assert rejected["consent_action"]["result"] == "banner_not_found"
    assert rejected["page"]["interactions"] == []
    assert rejected["reload"]["performed"] is False


def test_vodafone_onetrust_inline_reject_link(vodafone):
    """OneTrust modal; its "Reddet" is a custom inline link (a#rejectAllButton), not
    OneTrust's standard button, so a label rule finds it. Accept is the vendor button.
    OptanonConsent is set before any interaction (seen via document.cookie)."""
    untouched = vodafone["states"]["untouched"]
    ui = untouched["consent_ui"]
    assert "onetrust" in {c["id"] for c in ui["cmp"]}
    assert ui["banner"]["found"] is True
    assert ui["banner"]["rule"] == "cmp:onetrust"
    reject = _control(ui, "Reddet")
    assert (reject["tag"], reject["css_id"]) == ("a", "rejectAllButton")
    assert (reject["matched_role"], reject["rule"]) == ("reject", "label:reject")
    accept = _control(ui, "Çerezleri kabul et")
    assert (accept["css_id"], accept["rule"]) == (
        "onetrust-accept-btn-handler",
        "cmp:onetrust:accept",
    )
    assert untouched["page"]["interactions"] == []
    assert "OptanonConsent" in _cookie_names(untouched)

    rejected = vodafone["states"]["rejected"]
    _assert_rejected_and_reloaded(rejected, "Reddet")
    assert "OptanonAlertBoxClosed" in _cookie_names(rejected)


def test_yapikredi_custom_banner(yapikredi):
    """No known CMP; a fixed bottom bar with three links: Tercihler / Tümünü Reddet /
    Tümünü Kabul Et."""
    ui = yapikredi["states"]["untouched"]["consent_ui"]
    assert ui["cmp"] == []
    assert ui["banner"]["found"] is True
    assert ui["banner"]["rule"] == "generic:keywords"
    assert _control(ui, "Tercihler")["matched_role"] == "settings"
    assert _control(ui, "Tümünü Reddet")["rule"] == "label:reject"
    assert _control(ui, "Tümünü Kabul Et")["matched_role"] == "accept"

    _assert_rejected_and_reloaded(yapikredi["states"]["rejected"], "Tümünü Reddet")


def test_akbank_efilli_shadow_dom_div_controls(akbank):
    """Turkish CMP Efilli (window.efilliSdk, bundles.efilli.com), rendered in the open
    shadow root of <efilli-layout-dynamic>; its controls are clickable <div>s."""
    ui = akbank["states"]["untouched"]["consent_ui"]
    efilli = [c for c in ui["cmp"] if c["id"] == "efilli"]
    assert efilli and "global:efilliSdk" in efilli[0]["evidence"]
    assert ui["banner"]["found"] is True
    assert ui["banner"]["rule"] == "cmp:efilli"
    assert ui["banner"]["in_shadow_dom"] is True
    reject = _control(ui, "Tümünü Reddet")
    assert (reject["tag"], reject["matched_role"]) == ("div", "reject")
    assert _control(ui, "Tümünü Kabul Et")["matched_role"] == "accept"
    assert _control(ui, "Çerezleri Ayarla")["matched_role"] == "settings"

    _assert_rejected_and_reloaded(akbank["states"]["rejected"], "Tümünü Reddet")
