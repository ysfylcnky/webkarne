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

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "web_privacy"

CFG = {
    "max_url_length": 2048,
    "block_markers": {
        "headers": {"cf-mitigated": "challenge"},
        "statuses": [403, 429, 503],
        "titles": ["Just a moment...", "Access Denied"],
    },
}


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
    assert wp.IMPLEMENTED_STATES == ("untouched",)


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
