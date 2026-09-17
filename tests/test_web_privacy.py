"""Offline unit tests for the privacy collector's pure layer (dimension C).

No browser, no network: the browser I/O layer captures a plain "observation" dict,
and everything from there to the stored record is a pure function tested against
hand-written expected output (CLAUDE.md "expected output before code"). Live-browser
tests live in tests/test_web_privacy_network.py.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from karne.collectors import web_privacy as wp
from karne.collectors.dns_email import load_settings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "web_privacy"

# The real [web_privacy] section: label rules and block markers are tested as configured.
CFG = load_settings()["web_privacy"]
CONSENT = CFG["consent"]


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _obs(**overrides) -> dict:
    obs = _load("observation_loaded.json")
    obs.update(overrides)
    return obs


# --- whole state record against the hand-written fixture ---


def test_assemble_state_matches_hand_written_expected():
    assert wp.assemble_state(_load("observation_loaded.json"), CFG) == _load(
        "expected_state_loaded.json"
    )


def test_assemble_state_does_not_mutate_observation():
    obs = _load("observation_loaded.json")
    before = copy.deepcopy(obs)
    wp.assemble_state(obs, CFG)
    assert obs == before


# --- cookies ---


def test_cookie_values_are_never_recorded():
    cookies = wp.normalize_cookies(_load("observation_loaded.json")["cookies"])
    assert all("value" not in c for c in cookies)
    assert "s3cr3t" not in json.dumps(cookies)


def test_session_cookie_has_no_expiry():
    (c,) = wp.normalize_cookies(
        [
            {
                "name": "a",
                "value": "x",
                "domain": "d.tr",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )
    assert c["session"] is True
    assert c["expires"] is None


# --- requests ---


def test_long_url_is_truncated_and_flagged():
    long_url = "https://t.example/p?" + "x" * 100
    (r,) = wp.normalize_requests(
        [{"url": long_url, "resource_type": "image", "method": "GET"}], max_url_length=40
    )
    assert r["url"] == long_url[:40]
    assert r["url_truncated"] is True
    assert r["host"] == "t.example"  # host comes from the FULL url


def test_data_url_has_no_host():
    (r,) = wp.normalize_requests(
        [{"url": "data:image/png;base64,AAAA", "resource_type": "image", "method": "GET"}],
        max_url_length=2048,
    )
    assert r["host"] is None
    assert r["scheme"] == "data"
    assert r["status"] is None and r["failure"] is None


# --- outcome classification (rule 6: each failure is its own state) ---


def test_timeout_is_its_own_state():
    s = wp.assemble_state(
        _obs(
            navigation_error={"type": "TimeoutError", "message": "Timeout 30000ms exceeded."},
            main_response=None,
        ),
        CFG,
    )
    assert s["outcome"] == "timeout"
    assert s["error"] == {"kind": "TimeoutError", "message": "Timeout 30000ms exceeded."}


def test_dns_failure_is_dns_error():
    s = wp.assemble_state(
        _obs(
            navigation_error={
                "type": "Error",
                "message": "page.goto: net::ERR_NAME_NOT_RESOLVED at https://nope.invalid/",
            },
            main_response=None,
        ),
        CFG,
    )
    assert s["outcome"] == "dns_error"


def test_other_network_failure_is_navigation_error():
    s = wp.assemble_state(
        _obs(
            navigation_error={"type": "Error", "message": "net::ERR_CERT_DATE_INVALID"},
            main_response=None,
        ),
        CFG,
    )
    assert s["outcome"] == "navigation_error"


def test_missing_main_response_is_navigation_error():
    s = wp.assemble_state(_obs(main_response=None), CFG)
    assert s["outcome"] == "navigation_error"
    assert s["error"]["kind"] == "no_main_response"


def test_browser_error_overrides_everything():
    s = wp.assemble_state(
        _obs(browser_error="Target page, context or browser has been closed"), CFG
    )
    assert s["outcome"] == "browser_error"
    assert s["error"]["kind"] == "browser_error"


def test_blocked_by_marker_header_records_evidence():
    main = {"url": "https://x.tr/", "status": 403, "headers": {"cf-mitigated": "challenge"}}
    s = wp.assemble_state(_obs(main_response=main, title="Just a moment..."), CFG)
    assert s["outcome"] == "blocked"
    assert s["blocked_evidence"] == [
        "header:cf-mitigated=challenge",
        "status:403+title:Just a moment...",
    ]


def test_blocked_by_status_and_title():
    main = {"url": "https://x.tr/", "status": 403, "headers": {}}
    s = wp.assemble_state(_obs(main_response=main, title="Access Denied"), CFG)
    assert s["outcome"] == "blocked"
    assert s["blocked_evidence"] == ["status:403+title:Access Denied"]


def test_403_without_marker_is_http_error_not_blocked():
    main = {"url": "https://x.tr/", "status": 403, "headers": {}}
    s = wp.assemble_state(_obs(main_response=main, title="Yasak"), CFG)
    assert s["outcome"] == "http_error"
    assert s["blocked_evidence"] == []


def test_challenge_title_with_200_is_not_blocked():
    main = {"url": "https://x.tr/", "status": 200, "headers": {}}
    s = wp.assemble_state(_obs(main_response=main, title="Just a moment..."), CFG)
    assert s["outcome"] == "loaded"


def test_failure_keeps_whatever_was_observed():
    """A failed state is 'could not measure', but its observations are still raw data;
    the outcome (not an empty list) is what tells scoring it was not measured."""
    s = wp.assemble_state(
        _obs(navigation_error={"type": "TimeoutError", "message": "Timeout"}, main_response=None),
        CFG,
    )
    assert s["outcome"] == "timeout"
    assert len(s["cookies"]) == 3
    assert len(s["requests"]) == 4


def test_unloaded_page_has_no_load_timing():
    obs = _obs(timing={"goto_ms": 900, "dom_content_loaded_ms": 850.0, "load_ms": None})
    page = wp.assemble_state(obs, CFG)["page"]
    assert page["load_event_fired"] is False
    assert page["load_ms"] is None


# --- K-06 / K-07 guards ---


def test_untouched_state_must_have_no_interactions():
    with pytest.raises(ValueError, match="untouched"):
        wp.assemble_state(_obs(interactions=[{"action": "click", "target": "#accept"}]), CFG)


def test_not_run_state_record():
    assert wp.not_run_state("rejected") == {
        "consent_state": "rejected",
        "outcome": "not_run",
        "reason": "not_implemented",
    }


def test_consent_state_names():
    assert wp.CONSENT_STATES == ("untouched", "rejected", "accepted")
    assert wp.IMPLEMENTED_STATES == ("untouched", "rejected")


# --- user agent (K-16) ---


def test_user_agent_appends_identity():
    ua = wp.compose_user_agent(
        "Mozilla/5.0 Chrome/153.0.0.0 Safari/537.36", "WebKarne/1.0 (+https://webkarne.com)", True
    )
    assert ua == "Mozilla/5.0 Chrome/153.0.0.0 Safari/537.36 WebKarne/1.0 (+https://webkarne.com)"


def test_user_agent_identity_only_when_not_appending():
    assert wp.compose_user_agent("Mozilla/5.0", "WebKarne/1.0", False) == "WebKarne/1.0"


def test_missing_playwright_is_a_loud_collector_failure(monkeypatch):
    """Without the optional dependency the collector raises (-> scan-level error),
    it never returns an empty "no cookies" payload (rule 6)."""
    import sys

    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    with pytest.raises(RuntimeError, match="uv sync --group privacy"):
        wp.collect("example.com", {"http": {"user_agent": "WebKarne/1.0"}})


# --- scan status (batch registry) ---


def _payload_with(outcome: str) -> dict:
    return {
        "states": {
            "untouched": {"consent_state": "untouched", "outcome": outcome, "error": None},
            "rejected": wp.not_run_state("rejected"),
            "accepted": wp.not_run_state("accepted"),
        }
    }


@pytest.mark.parametrize(
    "outcome", ["loaded", "http_error", "blocked", "timeout", "dns_error", "navigation_error"]
)
def test_target_side_outcomes_are_a_completed_scan(outcome):
    assert wp.privacy_status(_payload_with(outcome)) == ("ok", None)


def test_local_browser_error_is_partial():
    payload = _payload_with("browser_error")
    payload["states"]["untouched"]["error"] = {"kind": "browser_error", "message": "crashed"}
    status, detail = wp.privacy_status(payload)
    assert status == "partial"
    assert "untouched" in detail and "crashed" in detail


def test_block_title_any_status():
    main = {"url": "https://x.tr/", "status": 200, "headers": {}}
    s = wp.assemble_state(_obs(main_response=main, title="İstek Engellendi"), CFG)
    assert s["outcome"] == "blocked"
    assert s["blocked_evidence"] == ["title:İstek Engellendi"]


# ===========================================================================
# Session 2: consent UI observation + the rejected state
# ===========================================================================


def test_assemble_rejected_state_matches_hand_written_expected():
    assert wp.assemble_state(_load("observation_rejected.json"), CFG) == _load(
        "expected_state_rejected.json"
    )


# --- labels (every label below was observed on a Turkish site, 2026-09-17) ---


@pytest.mark.parametrize(
    ("label", "role", "rule"),
    [
        ("Reddet", "reject", "label:reject"),
        ("Tümünü Reddet", "reject", "label:reject"),
        ("Tüm Çerezleri Reddet", "reject", "label:reject"),
        ("İsteğe Bağlı Çerezlerin Tümünü Reddet", "reject", "label:reject"),
        ("KABUL ETMİYORUM", "reject", "label:reject"),
        ("Yalnızca zorunlu çerezlerle devam et", "reject", "label:necessary_only"),
        ("Kabul Et", "accept", "label:accept"),
        ("Tümünü Kabul Et", "accept", "label:accept"),
        ("Tüm Tanımlama Bilgilerini Kabul Et", "accept", "label:accept"),
        ("Tümüne izin ver", "accept", "label:accept"),
        ("İsteğe Bağlı Çerezlerin Tümünü Kabul Et", "accept", "label:accept"),
        ("Ayarlar", "settings", "label:settings"),
        ("Tercihleri Yönet", "settings", "label:settings"),
        ("Çerezleri Ayarla", "settings", "label:settings"),
        ("Tanımlama Bilgisi Ayarları", "settings", "label:settings"),
        ("Çerez ayarlarını inceleyin", "settings", "label:settings"),
        ("Çerez Politikamız", None, None),
        ("buraya tıklayabilirsiniz.", None, None),
        ("", None, None),
    ],
)
def test_classify_label(label, role, rule):
    assert wp.classify_label(label, CONSENT) == (role, rule)


def test_normalize_label_is_turkish_aware():
    assert wp.normalize_label("  TÜMÜNÜ\n  REDDET ") == "tümünü reddet"
    assert wp.normalize_label("İSTEĞE") == "isteğe"  # not "i̇steğe" (no combining dot)
    # Upper-case I maps to "i", not "ı", so English labels survive ("DECLINE"); the
    # Turkish label rules therefore spell such letters as [ıi].
    assert wp.normalize_label("BAĞLI DECLINE") == "bağli decline"


def test_prose_is_never_classified():
    prose = (
        "Reddet seçeneğine tıklaman halinde tercih ve ilgi alanlarına yönelik "
        "sana özel bir deneyim sunamayacağız."
    )
    assert wp.classify_label(prose, CONSENT) == (None, None)


# --- consent UI assembly ---


def _ctl(text, *, tag="button", vendor_role=None, vendor_rule=None, **style):
    c = {
        "tag": tag,
        "text": text,
        "aria_label": None,
        "css_id": None,
        "rect": [10, 10, 100, 30],
        "visibility": "visible",
        "opacity": 1.0,
        "display": "block",
        "cursor": "pointer",
        "vendor_role": vendor_role,
        "vendor_rule": vendor_rule,
    }
    c.update(style)
    return c


def _raw(*candidates, cmp_evidence=None, tcf=False, frames_extra=()):
    frames = [
        {
            "frame_url": "https://x.tr/",
            "cmp_evidence": cmp_evidence or {},
            "tcf_api": tcf,
            "candidates": [
                {
                    "rule": rule,
                    "in_shadow_dom": shadow,
                    "rect": rect,
                    "visible": True,
                    "text": "Çerez metni",
                    "controls": controls,
                }
                for rule, shadow, rect, controls in candidates
            ],
        },
        *frames_extra,
    ]
    return {"scanned_at_ms": 5000, "error": None, "frames": frames}


def test_hidden_vendor_reject_is_recorded_but_not_clickable():
    """Modelled on dr.com.tr: Cookiebot's Decline button exists but is visibility:hidden,
    opacity 0. (The live site instead offers "Reddet" as a clickable <span> inside the
    banner prose, which the collector clicks — seen on the first live run, 2026-09-17.)"""
    decline = _ctl(
        "Reddet",
        vendor_role="reject",
        vendor_rule="cmp:cookiebot:reject",
        visibility="hidden",
        opacity=0.0,
    )
    controls = [
        decline,
        _ctl("Ayarlar", vendor_role="settings", vendor_rule="cmp:cookiebot:settings"),
        _ctl("Kabul Et", vendor_role="accept", vendor_rule="cmp:cookiebot:accept"),
    ]
    raw = _raw(
        ("cmp:cookiebot", False, [0, 500, 1366, 268], controls),
        cmp_evidence={"cookiebot": ["global:Cookiebot"]},
    )
    ui = wp.assemble_consent_ui(raw, CONSENT)
    assert ui["cmp"] == [{"id": "cookiebot", "evidence": ["global:Cookiebot"]}]
    assert ui["banner"]["found"] is True
    hidden = ui["controls"][0]
    assert hidden["visible"] is False
    assert (hidden["matched_role"], hidden["rule"]) == ("reject", "cmp:cookiebot:reject")
    assert wp.plan_reject(ui, CONSENT) == ("control_not_found", None)


def test_efilli_shadow_dom_div_is_clickable():
    controls = [
        _ctl("Çerez Aydınlatma Metni", tag="a"),
        _ctl("Tümünü Kabul Et", tag="div"),
        _ctl("Tümünü Reddet", tag="div"),
        _ctl("Çerezleri Ayarla", tag="a"),
    ]
    raw = _raw(
        ("cmp:efilli", True, [0, 650, 1366, 118], controls),
        cmp_evidence={"efilli": ["global:efilliSdk", "script:bundles.efilli.com"]},
    )
    ui = wp.assemble_consent_ui(raw, CONSENT)
    assert ui["banner"]["in_shadow_dom"] is True
    assert [c["matched_role"] for c in ui["controls"]] == [None, "accept", "reject", "settings"]
    assert wp.plan_reject(ui, CONSENT) == ("click", 2)


def test_vendor_reject_beats_label_and_reject_beats_necessary_only():
    controls = [
        _ctl("Yalnızca zorunlu çerezler"),
        _ctl("Reddet"),
        _ctl("Hayır", vendor_role="reject", vendor_rule="cmp:onetrust:reject"),
    ]
    ui = wp.assemble_consent_ui(_raw(("cmp:onetrust", False, [0, 0, 500, 300], controls)), CONSENT)
    assert wp.plan_reject(ui, CONSENT) == ("click", 2)
    ui["controls"][2]["visible"] = False
    assert wp.plan_reject(ui, CONSENT) == ("click", 1)
    ui["controls"][1]["visible"] = False
    assert wp.plan_reject(ui, CONSENT) == ("click", 0)


@pytest.mark.parametrize(
    "style",
    [
        {"rect": [10, 10, 0, 30]},
        {"visibility": "hidden"},
        {"opacity": 0.0},
        {"display": "none"},
    ],
)
def test_invisible_controls(style):
    controls = [_ctl("Reddet", **style), _ctl("Kabul Et")]
    ui = wp.assemble_consent_ui(_raw(("cmp:x", False, [0, 0, 500, 300], controls)), CONSENT)
    assert ui["controls"][0]["visible"] is False
    assert wp.plan_reject(ui, CONSENT) == ("control_not_found", None)


def test_generic_candidate_without_consent_controls_is_not_a_banner():
    link_bar = ("generic:keywords", False, [0, 0, 1366, 80], [_ctl("Çerez Politikası", tag="a")])
    ui = wp.assemble_consent_ui(_raw(link_bar), CONSENT)
    assert ui["banner"] == {"found": False}
    assert ui["controls"] == []
    assert ui["candidates_seen"] == 1
    assert wp.plan_reject(ui, CONSENT) == ("banner_not_found", None)


def test_smallest_generic_banner_wins_and_invisible_cmp_banner_is_skipped():
    big = ("generic:keywords", False, [0, 0, 1366, 768], [_ctl("Kabul Et")])
    small = ("generic:keywords", False, [0, 700, 1366, 68], [_ctl("Reddet"), _ctl("Kabul Et")])
    ui = wp.assemble_consent_ui(_raw(big, small), CONSENT)
    assert ui["banner"]["candidate_index"] == 1

    hidden_cmp = ("cmp:onetrust", False, [0, 0, 0, 0], [_ctl("Reddet")])
    raw = _raw(hidden_cmp, small)
    raw["frames"][0]["candidates"][0]["visible"] = False
    ui = wp.assemble_consent_ui(raw, CONSENT)
    assert (ui["banner"]["rule"], ui["banner"]["candidate_index"]) == ("generic:keywords", 1)


def test_cmp_banner_beats_generic_and_iframe_banner_is_found():
    generic = ("generic:keywords", False, [0, 700, 1366, 68], [_ctl("Kabul Et")])
    iframe = {
        "frame_url": "https://cmp.example/notice",
        "cmp_evidence": {"sourcepoint": ["selector:x"], "didomi": []},
        "tcf_api": True,
        "candidates": [
            {
                "rule": "cmp:sourcepoint",
                "in_shadow_dom": False,
                "rect": [0, 0, 600, 400],
                "visible": True,
                "text": "x" * 5000,
                "controls": [_ctl("Reject all")],
            }
        ],
    }
    ui = wp.assemble_consent_ui(_raw(generic, frames_extra=[iframe]), CONSENT)
    assert ui["cmp"] == [{"id": "sourcepoint", "evidence": ["selector:x"]}]
    assert ui["tcf_api"] is True
    banner = ui["banner"]
    assert (banner["frame_index"], banner["frame_url"]) == (1, "https://cmp.example/notice")
    assert len(banner["text"]) == CONSENT["banner_text_max_chars"]
    assert banner["text_truncated"] is True


def test_missing_consent_scan_is_none():
    assert wp.assemble_consent_ui(None, CONSENT) is None


def test_consent_scan_error_is_kept():
    raw = {"scanned_at_ms": 100, "error": "Execution context was destroyed", "frames": []}
    ui = wp.assemble_consent_ui(raw, CONSENT)
    assert ui["error"] == "Execution context was destroyed"
    assert ui["banner"] == {"found": False}


# --- rejected-state guards (K-06: one reject click at most) ---


def _rejected(**overrides):
    obs = _load("observation_rejected.json")
    obs.update(overrides)
    return obs


def test_rejected_state_allows_at_most_one_reject_click():
    two = [{"action": "click", "role": "reject", "control_index": 1, "t_ms": 1}] * 2
    with pytest.raises(ValueError, match="at most one"):
        wp.assemble_state(_rejected(interactions=two), CFG)


def test_rejected_state_never_clicks_accept():
    accept = [{"action": "click", "role": "accept", "control_index": 2, "t_ms": 1}]
    with pytest.raises(ValueError, match="reject"):
        wp.assemble_state(_rejected(interactions=accept), CFG)


def test_clicked_result_requires_the_interaction():
    with pytest.raises(ValueError, match="clicked"):
        wp.assemble_state(_rejected(interactions=[]), CFG)


def test_unclicked_rejected_state_has_no_reload():
    obs = _rejected(
        interactions=[],
        consent_action={
            "action": "reject",
            "result": "control_not_found",
            "control_index": None,
            "clicked_at_ms": None,
            "navigated_after_click": None,
            "error": None,
        },
        reload={
            "performed": False,
            "status": None,
            "final_url": None,
            "goto_ms": None,
            "error": None,
        },
        consent_ui_after_reload_raw=None,
    )
    s = wp.assemble_state(obs, CFG)
    assert s["consent_action"]["control"] is None
    assert s["consent_ui_after_reload"] is None
    assert s["reload"]["performed"] is False
