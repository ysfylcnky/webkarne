"""Privacy & tracking collector — dimension C (Sprint 4).

Single entry point: ``collect(domain, settings) -> dict``. A real Chromium (via
Playwright) visits the site's homepage once per consent state of PLAN.md K-06
(untouched / rejected / accepted), each in a fresh browser context, and records what
it observed as RAW, UNINTERPRETED data (CLAUDE.md rule 1): every cookie through the
browser protocol (HttpOnly included, values never), storage key names (values
never), and every network request. No "tracker" label, no first/third-party
decision, no score: those belong to the analysis/scoring layers (K-02, K-16).

Passive, visitor-equivalent measurement only (K-07): the homepage, no link
following, no forms, no login. In the "untouched" state there is no interaction at
all; the page is observed for a fixed window. Bot protection is never bypassed: an
observable block is recorded as outcome "blocked" with its evidence (rule 6).

Sprint 4 · Session 1 implements the "untouched" state; the other two are recorded as
``outcome="not_run"``.

Layering (so the logic is testable without a browser):

* the **pure layer** (``assemble_state`` and helpers) turns a plain "observation"
  dict into the stored state record — unit-tested against fixtures;
* the **browser I/O layer** (``_observe_state``) drives Playwright and captures that
  observation dict, nothing more.

Playwright is an optional dependency (uv group ``privacy``, K-16) and is imported
lazily, so the rest of Karne runs without it.
"""

from __future__ import annotations

import contextlib
import time
import urllib.parse
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

from karne.collectors.dns_email import _RateLimiter, config_hash, load_settings
from karne.models import (
    CONSENT_ACCEPTED,
    CONSENT_REJECTED,
    CONSENT_UNTOUCHED,
    STATUS_OK,
    STATUS_PARTIAL,
)

COLLECTOR = "web_privacy"
COLLECTOR_VERSION = "0.1.0"

CONSENT_STATES = (CONSENT_UNTOUCHED, CONSENT_REJECTED, CONSENT_ACCEPTED)
IMPLEMENTED_STATES = (CONSENT_UNTOUCHED,)

# Outcome values of one consent-state record (PLAN.md K-16). Only OUTCOME_LOADED
# means "measured"; every other value is a distinct "could not measure" state.
OUTCOME_LOADED = "loaded"
OUTCOME_HTTP_ERROR = "http_error"
OUTCOME_BLOCKED = "blocked"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_DNS_ERROR = "dns_error"
OUTCOME_NAVIGATION_ERROR = "navigation_error"
OUTCOME_BROWSER_ERROR = "browser_error"
OUTCOME_NOT_RUN = "not_run"

# Chromium net error names that mean the host name did not resolve. Chromium uses
# the system resolver, not the fixed K-11 resolvers of dimension A.
_DNS_NET_ERRORS = ("ERR_NAME_NOT_RESOLVED", "ERR_NAME_RESOLUTION_FAILED")

_INSTALL_HINT = (
    "Playwright is not installed. Dimension C needs the optional 'privacy' group: "
    "`uv sync --group privacy` then `uv run playwright install chromium`."
)


# ---------------------------------------------------------------------------
# Pure layer (no browser, no network)
# ---------------------------------------------------------------------------


def compose_user_agent(browser_ua: str, identity: str, append: bool) -> str:
    """The browser's own UA with the project identity appended (K-16), or the
    identity alone when appending is disabled."""
    if not append:
        return identity
    return f"{browser_ua} {identity}".strip()


def not_run_state(consent_state: str) -> dict[str, Any]:
    """Record for a consent state that was not measured in this collector version."""
    return {"consent_state": consent_state, "outcome": OUTCOME_NOT_RUN, "reason": "not_implemented"}


def normalize_cookies(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Browser-protocol cookies -> stored cookie observations, WITHOUT values.

    Playwright reports a session cookie with ``expires == -1``; it is stored as
    ``expires=None, session=True``. Sorted by (domain, name, path) so the record does
    not depend on the browser's internal ordering.
    """
    out: list[dict[str, Any]] = []
    for c in raw:
        expires = c.get("expires")
        session = expires is None or expires < 0
        out.append(
            {
                "name": c.get("name"),
                "domain": c.get("domain"),
                "path": c.get("path"),
                "expires": None if session else expires,
                "session": session,
                "http_only": bool(c.get("httpOnly")),
                "secure": bool(c.get("secure")),
                "same_site": c.get("sameSite"),
                "partition_key": c.get("partitionKey"),
            }
        )
    out.sort(key=lambda c: ((c["domain"] or "").lower(), c["name"] or "", c["path"] or ""))
    return out


def normalize_requests(raw: list[dict[str, Any]], *, max_url_length: int) -> list[dict[str, Any]]:
    """Captured request events -> stored request observations, in observed order.

    The host is taken from the full URL before the URL is cut to ``max_url_length``.
    The host is recorded as-is (lower-cased); first/third-party is NOT decided here.
    """
    out: list[dict[str, Any]] = []
    for r in raw:
        url = r.get("url") or ""
        try:
            parts = urllib.parse.urlsplit(url)
            host = parts.hostname
            scheme = parts.scheme or None
        except ValueError:  # malformed URL: keep the raw string, no host
            host, scheme = None, None
        truncated = len(url) > max_url_length
        out.append(
            {
                "url": url[:max_url_length] if truncated else url,
                "url_truncated": truncated,
                "host": host,
                "scheme": scheme,
                "resource_type": r.get("resource_type"),
                "method": r.get("method"),
                "status": r.get("status"),
                "failure": r.get("failure"),
                "response_bytes": r.get("response_bytes"),
                "frame": r.get("frame"),
                "is_navigation": r.get("is_navigation"),
            }
        )
    return out


def block_evidence(
    main_response: dict[str, Any] | None, title: str | None, markers: dict[str, Any]
) -> list[str]:
    """Observable bot-protection signals on the main document (config-driven).

    A marker header counts on its own; a challenge title counts only together with
    one of the configured statuses (a 200 page titled "Access Denied" is not a block).
    """
    if not main_response:
        return []
    evidence: list[str] = []
    headers = {k.lower(): str(v) for k, v in (main_response.get("headers") or {}).items()}
    for name, value in (markers.get("headers") or {}).items():
        observed = headers.get(name.lower())
        if observed is not None and value.lower() in observed.lower():
            evidence.append(f"header:{name.lower()}={observed}")
    status = main_response.get("status")
    if status in (markers.get("statuses") or []) and title:
        for t in markers.get("titles") or []:
            if title.strip() == t:
                evidence.append(f"status:{status}+title:{t}")
    return evidence


def classify_outcome(observation: dict[str, Any], evidence: list[str]) -> tuple[str, dict | None]:
    """Map an observation to (outcome, error). Each failure mode stays distinct."""
    if observation.get("browser_error"):
        return OUTCOME_BROWSER_ERROR, {
            "kind": "browser_error",
            "message": observation["browser_error"],
        }
    nav = observation.get("navigation_error")
    if nav:
        kind, message = nav.get("type"), nav.get("message") or ""
        error = {"kind": kind, "message": message}
        if kind == "TimeoutError":
            return OUTCOME_TIMEOUT, error
        if any(code in message for code in _DNS_NET_ERRORS):
            return OUTCOME_DNS_ERROR, error
        return OUTCOME_NAVIGATION_ERROR, error
    main = observation.get("main_response")
    if not main:
        return OUTCOME_NAVIGATION_ERROR, {
            "kind": "no_main_response",
            "message": "navigation returned no main document response",
        }
    if evidence:
        return OUTCOME_BLOCKED, None
    status = main.get("status")
    if isinstance(status, int) and status >= 400:
        return OUTCOME_HTTP_ERROR, None
    return OUTCOME_LOADED, None


def assemble_state(observation: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Build the stored record of one consent state from a captured observation.

    Whatever was observed is kept even when the outcome is a failure: raw data stays
    raw, and the ``outcome`` (never an empty list) tells later layers whether the
    state was measured (rule 6).
    """
    consent_state = observation.get("consent_state")
    interactions = list(observation.get("interactions") or [])
    if consent_state == CONSENT_UNTOUCHED and interactions:
        raise ValueError("the untouched consent state must have no interactions (K-06)")

    main = observation.get("main_response")
    title = observation.get("title")
    evidence = block_evidence(main, title, cfg.get("block_markers") or {})
    outcome, error = classify_outcome(observation, evidence)

    final_url = observation.get("final_url") or (main or {}).get("url")
    try:
        final_host = urllib.parse.urlsplit(final_url).hostname if final_url else None
    except ValueError:
        final_host = None
    timing = observation.get("timing") or {}
    load_ms = timing.get("load_ms")

    storage = observation.get("storage") or {}
    raw_requests = observation.get("requests") or []
    request_count = observation.get("request_count", len(raw_requests))

    return {
        "consent_state": consent_state,
        "outcome": outcome,
        "error": error,
        "blocked_evidence": evidence,
        "started_at": observation.get("started_at"),
        "finished_at": observation.get("finished_at"),
        "page": {
            "requested_url": observation.get("requested_url"),
            "final_url": final_url,
            "final_host": final_host,
            "main_status": (main or {}).get("status"),
            "redirects": list(observation.get("redirects") or []),
            "title": title,
            "goto_ms": timing.get("goto_ms"),
            "dom_content_loaded_ms": timing.get("dom_content_loaded_ms"),
            "load_event_fired": load_ms is not None,
            "load_ms": load_ms,
            "observe_seconds": observation.get("observe_seconds"),
            "interactions": interactions,
        },
        "cookies": normalize_cookies(observation.get("cookies") or []),
        "storage": {
            "origin": storage.get("origin"),
            "local_storage_keys": sorted(storage.get("local") or []),
            "session_storage_keys": sorted(storage.get("session") or []),
            "indexeddb_names": sorted(storage.get("indexeddb") or []),
            "error": storage.get("error"),
        },
        "requests": normalize_requests(
            raw_requests, max_url_length=int(cfg.get("max_url_length", 2048))
        ),
        "request_count": request_count,
        "requests_truncated": request_count > len(raw_requests),
    }


def privacy_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Scan status for the batch registry.

    Target-side outcomes (timeout, dns_error, blocked, ...) are normal measurement
    results kept inside each state record, like a DNS servfail in dimension A. Only a
    local browser failure makes the scan ``partial``; a whole-collector crash is
    caught by the caller and becomes a scan-level error.
    """
    failed = [
        f"{name}: {(state.get('error') or {}).get('message')}"
        for name, state in (payload.get("states") or {}).items()
        if state.get("outcome") == OUTCOME_BROWSER_ERROR
    ]
    if failed:
        return STATUS_PARTIAL, "; ".join(failed)
    return STATUS_OK, None


# ---------------------------------------------------------------------------
# Browser I/O layer (Playwright) — captures observations, interprets nothing
# ---------------------------------------------------------------------------

# Navigation Timing of the main document, relative to navigation start (ms).
# loadEventEnd is 0 until the load event has finished -> reported as null.
_TIMING_JS = """() => {
  const n = performance.getEntriesByType('navigation')[0];
  if (!n) return null;
  return {dcl: n.domContentLoadedEventEnd || null, load: n.loadEventEnd || null};
}"""

# Storage key NAMES only (values may hold personal data). IndexedDB database names
# where the API exists.
_STORAGE_JS = """async () => {
  const out = {origin: location.origin, local: [], session: [], indexeddb: [], error: null};
  try { out.local = Object.keys(window.localStorage); } catch (e) { out.error = 'local: ' + e; }
  try { out.session = Object.keys(window.sessionStorage); }
  catch (e) { out.error = (out.error ? out.error + '; ' : '') + 'session: ' + e; }
  try {
    if (indexedDB.databases) {
      out.indexeddb = (await indexedDB.databases()).map(d => d.name).filter(Boolean);
    }
  } catch (e) { out.error = (out.error ? out.error + '; ' : '') + 'indexeddb: ' + e; }
  return out;
}"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _playwright_version() -> str | None:
    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return None


def _request_record(req: Any, main_frame: Any) -> dict[str, Any]:
    """Collect one request's fields after the observation window (round trips allowed)."""
    from playwright.sync_api import Error as PlaywrightError

    rec: dict[str, Any] = {
        "url": req.url,
        "resource_type": req.resource_type,
        "method": req.method,
        "status": None,
        "failure": req.failure,
        "response_bytes": None,
        "frame": None,
        "is_navigation": None,
    }
    try:
        rec["is_navigation"] = req.is_navigation_request()
        rec["frame"] = "main" if req.frame == main_frame else "sub"
    except PlaywrightError:  # service-worker requests have no frame; fields stay None
        pass
    if rec["failure"] is None:
        try:
            resp = req.response()
            if resp is not None:
                rec["status"] = resp.status
            rec["response_bytes"] = req.sizes().get("responseBodySize")
        except PlaywrightError:  # request vanished with its frame; fields stay None
            pass
    return rec


def _evaluate(page: Any, script: str) -> tuple[Any, str | None]:
    """Run a read-only script; a page that navigated away mid-read is not a browser
    failure, so the error is returned for the record instead of raised."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        return page.evaluate(script), None
    except PlaywrightError as exc:
        return None, _short(exc)


def _redirect_chain(response: Any) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    req = response.request.redirected_from
    while req is not None:
        resp = req.response()
        hops.append({"url": req.url, "status": resp.status if resp is not None else None})
        req = req.redirected_from
    hops.reverse()
    return hops


def _observe_state(
    browser: Any,
    consent_state: str,
    start_url: str,
    user_agent: str,
    cfg: dict[str, Any],
    limiter: _RateLimiter,
) -> dict[str, Any]:
    """Visit ``start_url`` in a fresh context and capture a raw observation dict.

    Untouched state: no click, no scroll, no input — navigation, then a fixed wait.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    nav_timeout_ms = float(cfg.get("navigation_timeout_seconds", 30.0)) * 1000
    observe_s = float(cfg.get("observe_seconds", 15.0))
    budget_s = float(cfg.get("state_budget_seconds", 60.0))
    max_requests = int(cfg.get("max_requests", 1000))

    obs: dict[str, Any] = {
        "consent_state": consent_state,
        "started_at": _now(),
        "requested_url": start_url,
        "navigation_error": None,
        "browser_error": None,
        "main_response": None,
        "redirects": [],
        "final_url": None,
        "title": None,
        "timing": {"goto_ms": None, "dom_content_loaded_ms": None, "load_ms": None},
        "observe_seconds": observe_s,
        "interactions": [],
        "cookies": [],
        "storage": {},
        "requests": [],
        "request_count": 0,
    }
    captured: list[Any] = []
    t0 = time.monotonic()
    context = None
    try:
        context = browser.new_context(
            user_agent=user_agent,
            locale=cfg.get("locale", "tr-TR"),
            timezone_id=cfg.get("timezone", "Europe/Istanbul"),
            viewport={
                "width": int(cfg.get("viewport_width", 1366)),
                "height": int(cfg.get("viewport_height", 768)),
            },
            service_workers="block",
        )
        page = context.new_page()

        def _on_request(req: Any) -> None:
            obs["request_count"] += 1
            if len(captured) < max_requests:
                captured.append(req)

        page.on("request", _on_request)

        limiter.acquire()
        response = None
        try:
            response = page.goto(start_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
            obs["timing"]["goto_ms"] = round((time.monotonic() - t0) * 1000)
        except PlaywrightTimeoutError as exc:
            obs["navigation_error"] = {"type": "TimeoutError", "message": str(exc)}
        except PlaywrightError as exc:
            obs["navigation_error"] = {"type": "Error", "message": str(exc)}

        if obs["navigation_error"] is None:
            if response is not None:
                obs["main_response"] = {
                    "url": response.url,
                    "status": response.status,
                    "headers": response.all_headers(),
                }
                obs["redirects"] = _redirect_chain(response)
            remaining_ms = (budget_s - (time.monotonic() - t0) - observe_s) * 1000
            if remaining_ms > 0:
                # load never fired within budget: recorded as load_ms=None
                with contextlib.suppress(PlaywrightTimeoutError):
                    page.wait_for_load_state("load", timeout=remaining_ms)
            page.wait_for_timeout(observe_s * 1000)  # fixed observation window, no input
            timing, _ = _evaluate(page, _TIMING_JS)
            obs["timing"]["dom_content_loaded_ms"] = (timing or {}).get("dcl")
            obs["timing"]["load_ms"] = (timing or {}).get("load")
            obs["final_url"] = page.url
            obs["title"], _ = _evaluate(page, "() => document.title")
            storage, storage_error = _evaluate(page, _STORAGE_JS)
            obs["storage"] = storage if storage is not None else {"error": storage_error}

        obs["cookies"] = context.cookies()
        obs["requests"] = [_request_record(r, page.main_frame) for r in captured]
    except PlaywrightError as exc:
        obs["browser_error"] = _short(exc)
    finally:
        if context is not None:
            with contextlib.suppress(PlaywrightError):
                context.close()
        obs["finished_at"] = _now()
    return obs


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect(domain: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the dimension-C measurement for ``domain`` and return the raw payload."""
    settings = settings if settings is not None else load_settings()
    cfg = settings.get("web_privacy", {})
    identity = settings.get("http", {}).get("user_agent", f"karne/{COLLECTOR_VERSION}")
    host = domain.strip().lower().rstrip(".")
    start_url = f"https://{host}/"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(_INSTALL_HINT) from exc

    min_interval = float(cfg.get("min_interval_seconds", 1.0))
    limiter = _RateLimiter(1.0 / min_interval if min_interval > 0 else 0.0)
    headless = bool(cfg.get("headless", True))

    payload: dict[str, Any] = {
        "collector": COLLECTOR,
        "collector_version": COLLECTOR_VERSION,
        "input_domain": domain,
        "domain": host,
        "collected_at": _now(),
        "config_hash": config_hash(settings),
        "start_url": start_url,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            probe = browser.new_page()
            browser_ua = probe.evaluate("() => navigator.userAgent")
            probe.close()
            user_agent = compose_user_agent(
                browser_ua, identity, bool(cfg.get("append_identity_to_user_agent", True))
            )
            payload["browser"] = {
                "engine": "chromium",
                "browser_version": browser.version,
                "playwright_version": _playwright_version(),
                "headless": headless,
                "user_agent": user_agent,
                "locale": cfg.get("locale", "tr-TR"),
                "timezone": cfg.get("timezone", "Europe/Istanbul"),
                "viewport": {
                    "width": int(cfg.get("viewport_width", 1366)),
                    "height": int(cfg.get("viewport_height", 768)),
                },
            }
            states: dict[str, Any] = {}
            for state in CONSENT_STATES:
                if state not in IMPLEMENTED_STATES:
                    states[state] = not_run_state(state)
                    continue
                obs = _observe_state(browser, state, start_url, user_agent, cfg, limiter)
                states[state] = assemble_state(obs, cfg)
            payload["states"] = states
        finally:
            browser.close()
    return payload
