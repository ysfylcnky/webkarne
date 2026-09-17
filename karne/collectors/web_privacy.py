"""Privacy & tracking collector — dimension C (Sprint 4).

Single entry point: ``collect(domain, settings) -> dict``. A real Chromium (via
Playwright) visits the site's homepage once per consent state of PLAN.md K-06
(untouched / rejected / accepted), each in a fresh browser context, and records what
it observed as RAW, UNINTERPRETED data (CLAUDE.md rule 1): every cookie through the
browser protocol (HttpOnly included, values never), storage key names (values
never), every network request, and what the consent UI looked like. No "tracker"
label, no first/third-party decision, no "dark pattern" verdict, no score: those
belong to the analysis/scoring layers (K-02, K-16).

Passive, visitor-equivalent measurement only (K-07): the homepage, no link
following, no forms, no login. "untouched" has no interaction at all. "rejected"
clicks the banner's own visible first-layer reject control once, observes, reloads
the homepage once and observes again (K-16 addendum). Bot protection is never
bypassed: an observable block is recorded as outcome "blocked" with its evidence.

Sprint 4 implements "untouched" (Session 1) and "rejected" (Session 2); "accepted" is
recorded as ``outcome="not_run"``.

Layering (so the logic is testable without a browser):

* the **pure layer** (``assemble_state``, ``assemble_consent_ui``, ``plan_reject``
  and helpers) turns plain "observation" dicts into stored records and decides which
  control a reject click targets — unit-tested against fixtures;
* the **browser I/O layer** (``_observe_state``, ``_scan_consent_ui``) drives
  Playwright and captures those observation dicts; it clicks only what
  ``plan_reject`` chose.

Playwright is an optional dependency (uv group ``privacy``, K-16) and is imported
lazily, so the rest of Karne runs without it.
"""

from __future__ import annotations

import contextlib
import re
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
COLLECTOR_VERSION = "0.2.0"

CONSENT_STATES = (CONSENT_UNTOUCHED, CONSENT_REJECTED, CONSENT_ACCEPTED)
IMPLEMENTED_STATES = (CONSENT_UNTOUCHED, CONSENT_REJECTED)

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

# Request phases of the rejected state (untouched requests carry phase None).
PHASE_BEFORE_ACTION = "before_action"
PHASE_AFTER_ACTION = "after_action"
PHASE_AFTER_RELOAD = "after_reload"

# consent_action.result values.
ACTION_CLICKED = "clicked"
ACTION_BANNER_NOT_FOUND = "banner_not_found"
ACTION_CONTROL_NOT_FOUND = "control_not_found"
ACTION_CLICK_FAILED = "click_failed"

ROLE_REJECT = "reject"
_CONSENT_ROLES = ("reject", "accept")  # a generic candidate needs one to be a banner

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


def normalize_storage(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Captured storage key names -> stored record (names only, sorted)."""
    raw = raw or {}
    return {
        "origin": raw.get("origin"),
        "local_storage_keys": sorted(raw.get("local") or []),
        "session_storage_keys": sorted(raw.get("session") or []),
        "indexeddb_names": sorted(raw.get("indexeddb") or []),
        "error": raw.get("error"),
    }


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
                "t_ms": r.get("t_ms"),
                "phase": r.get("phase"),
            }
        )
    return out


def block_evidence(
    main_response: dict[str, Any] | None, title: str | None, markers: dict[str, Any]
) -> list[str]:
    """Observable bot-protection signals on the main document (config-driven).

    A marker header counts on its own; a challenge title counts together with one of
    the configured statuses (a 200 page titled "Access Denied" is not a block), except
    titles listed in ``titles_any_status`` (block pages served with 200).
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
    stripped = title.strip() if title else ""
    if stripped and status in (markers.get("statuses") or []):
        for t in markers.get("titles") or []:
            if stripped == t:
                evidence.append(f"status:{status}+title:{t}")
    if stripped:
        for t in markers.get("titles_any_status") or []:
            if stripped == t:
                evidence.append(f"title:{t}")
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


# --- consent UI -------------------------------------------------------------


def normalize_label(text: str | None) -> str:
    """Turkish-aware lower-case with collapsed whitespace ("İ" -> "i", not "i̇")."""
    t = (text or "").replace("İ", "i").lower().replace("̇", "")
    return " ".join(t.split())


def classify_label(text: str | None, consent_cfg: dict[str, Any]) -> tuple[str | None, str | None]:
    """First configured label rule matching the control text -> (role, "label:<id>").

    Empty labels and labels longer than ``max_label_chars`` (prose, not a control
    caption) are never classified.
    """
    norm = normalize_label(text)
    if not norm or len(norm) > int(consent_cfg.get("max_label_chars", 80)):
        return None, None
    for rule in consent_cfg.get("label_rules") or []:
        if re.search(rule["pattern"], norm):
            return rule["role"], f"label:{rule['id']}"
    return None, None


def is_visible(item: dict[str, Any]) -> bool:
    """Visible to a visitor: non-empty box, not hidden, effective opacity > 0, displayed."""
    rect = item.get("rect") or []
    opacity = item.get("opacity")
    return (
        len(rect) == 4
        and rect[2] > 0
        and rect[3] > 0
        and (item.get("visibility") or "visible") == "visible"
        and (1.0 if opacity is None else float(opacity)) > 0
        and item.get("display") != "none"
    )


_CONTROL_FIELDS = (
    "tag",
    "text",
    "aria_label",
    "css_id",
    "rect",
    "visibility",
    "opacity",
    "display",
    "cursor",
)


def _control_record(raw: dict[str, Any], consent_cfg: dict[str, Any]) -> dict[str, Any]:
    rec = {k: raw.get(k) for k in _CONTROL_FIELDS}
    rec["tag"] = (raw.get("tag") or "").lower() or None
    rec["text"] = " ".join((raw.get("text") or "").split())
    rec["visible"] = is_visible(raw)
    if raw.get("vendor_role"):
        rec["matched_role"], rec["rule"] = raw["vendor_role"], raw.get("vendor_rule")
    else:
        rec["matched_role"], rec["rule"] = classify_label(
            rec["text"] or raw.get("aria_label"), consent_cfg
        )
    return rec


def assemble_consent_ui(
    raw: dict[str, Any] | None, consent_cfg: dict[str, Any]
) -> dict[str, Any] | None:
    """Captured consent-UI scan (all frames) -> stored ``consent_ui`` observation.

    Banner choice: the first visible CMP-selector candidate (frame order); otherwise
    the smallest visible generic candidate that holds a visible reject/accept
    control. Every control of the chosen banner is recorded, hidden ones included.
    """
    if raw is None:
        return None
    evidence: dict[str, list[str]] = {}
    tcf_api = False
    cmp_pick: tuple | None = None
    generic: list[tuple] = []
    seen = 0
    for fi, frame in enumerate(raw.get("frames") or []):
        for cmp_id, items in (frame.get("cmp_evidence") or {}).items():
            for item in items or []:
                bucket = evidence.setdefault(cmp_id, [])
                if item not in bucket:
                    bucket.append(item)
        tcf_api = tcf_api or bool(frame.get("tcf_api"))
        for ci, cand in enumerate(frame.get("candidates") or []):
            seen += 1
            if not cand.get("visible"):
                continue
            controls = [_control_record(c, consent_cfg) for c in cand.get("controls") or []]
            entry = (fi, ci, frame, cand, controls)
            if (cand.get("rule") or "").startswith("cmp:"):
                if cmp_pick is None:
                    cmp_pick = entry
            elif any(c["visible"] and c["matched_role"] in _CONSENT_ROLES for c in controls):
                generic.append(entry)

    chosen = cmp_pick
    if chosen is None and generic:
        chosen = min(generic, key=lambda e: _area(e[3].get("rect")))

    banner: dict[str, Any] = {"found": False}
    controls: list[dict[str, Any]] = []
    if chosen is not None:
        fi, ci, frame, cand, controls = chosen
        limit = int(consent_cfg.get("banner_text_max_chars", 2000))
        text = cand.get("text") or ""
        banner = {
            "found": True,
            "rule": cand.get("rule"),
            "frame_url": frame.get("frame_url"),
            "frame_index": fi,
            "candidate_index": ci,
            "in_shadow_dom": bool(cand.get("in_shadow_dom")),
            "rect": cand.get("rect"),
            "text": text[:limit],
            "text_truncated": len(text) > limit,
        }
    return {
        "scanned_at_ms": raw.get("scanned_at_ms"),
        "cmp": [{"id": cmp_id, "evidence": items} for cmp_id, items in evidence.items()],
        "tcf_api": tcf_api,
        "banner": banner,
        "controls": controls,
        "candidates_seen": seen,
        "error": raw.get("error"),
    }


def _area(rect: list[float] | None) -> float:
    return rect[2] * rect[3] if rect and len(rect) == 4 else 0.0


def plan_reject(
    consent_ui: dict[str, Any] | None, consent_cfg: dict[str, Any]
) -> tuple[str, int | None]:
    """Which control a reject click may target: ("click", index) or why none.

    Only a VISIBLE control of the chosen banner with the reject role qualifies. A
    vendor (CMP selector) rule beats a label rule; label rules rank in config order;
    ties go to document order.
    """
    if not consent_ui or not consent_ui["banner"].get("found"):
        return ACTION_BANNER_NOT_FOUND, None
    order = {f"label:{r['id']}": i for i, r in enumerate(consent_cfg.get("label_rules") or [])}
    candidates = [
        (0 if (c["rule"] or "").startswith("cmp:") else 1 + order.get(c["rule"], len(order)), i)
        for i, c in enumerate(consent_ui["controls"])
        if c["visible"] and c["matched_role"] == ROLE_REJECT
    ]
    if not candidates:
        return ACTION_CONTROL_NOT_FOUND, None
    return "click", min(candidates)[1]


def _check_interactions(
    consent_state: str | None, interactions: list[dict[str, Any]], action: dict[str, Any]
) -> None:
    """K-06/K-07 guards: untouched never interacts; rejected clicks one reject control
    at most, and only when the recorded action says it clicked."""
    if consent_state == CONSENT_UNTOUCHED and interactions:
        raise ValueError("the untouched consent state must have no interactions (K-06)")
    if consent_state != CONSENT_REJECTED:
        return
    if len(interactions) > 1:
        raise ValueError("the rejected consent state allows at most one interaction (K-06)")
    if any(i.get("action") != "click" or i.get("role") != ROLE_REJECT for i in interactions):
        raise ValueError("the rejected consent state may only click a reject control (K-07)")
    if (action.get("result") == ACTION_CLICKED) != bool(interactions):
        raise ValueError("consent_action result 'clicked' must match exactly one reject click")


def assemble_state(observation: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Build the stored record of one consent state from a captured observation.

    Whatever was observed is kept even when the outcome is a failure: raw data stays
    raw, and the ``outcome`` (never an empty list) tells later layers whether the
    state was measured (rule 6).
    """
    consent_state = observation.get("consent_state")
    consent_cfg = cfg.get("consent") or {}
    interactions = list(observation.get("interactions") or [])
    action = dict(observation.get("consent_action") or {})
    _check_interactions(consent_state, interactions, action)

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

    raw_requests = observation.get("requests") or []
    request_count = observation.get("request_count", len(raw_requests))
    consent_ui = assemble_consent_ui(observation.get("consent_ui_raw"), consent_cfg)

    record: dict[str, Any] = {
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
        "storage": normalize_storage(observation.get("storage")),
        "requests": normalize_requests(
            raw_requests, max_url_length=int(cfg.get("max_url_length", 2048))
        ),
        "request_count": request_count,
        "requests_truncated": request_count > len(raw_requests),
        "consent_ui": consent_ui,
    }
    if consent_state == CONSENT_REJECTED:
        index = action.get("control_index")
        control = None
        if action.get("result") == ACTION_CLICKED and consent_ui and index is not None:
            c = consent_ui["controls"][index]
            control = {k: c.get(k) for k in ("tag", "text", "css_id", "matched_role", "rule")}
        action["control"] = control
        record["consent_action"] = action
        record["reload"] = dict(observation.get("reload") or {"performed": False})
        record["consent_ui_after_reload"] = assemble_consent_ui(
            observation.get("consent_ui_after_reload_raw"), consent_cfg
        )
        record["snapshots"] = [
            {
                "phase": s.get("phase"),
                "at_ms": s.get("at_ms"),
                "cookies": normalize_cookies(s.get("cookies") or []),
                "storage": normalize_storage(s.get("storage")),
            }
            for s in observation.get("snapshots") or []
        ]
    return record


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

# Read-only consent-UI scan of ONE frame. Finds banner candidates (CMP selectors, and
# visible fixed/sticky/dialog elements whose text holds a banner keyword), through open
# shadow roots, and lists every clickable inside each candidate with geometry and
# computed style. Returns {data, elements}: elements[c][k] is the DOM node of
# data.candidates[c].controls[k], so the Python side can click exactly the chosen one.
_CONSENT_JS = r"""(cfg) => {
  const CLICKABLE = 'button,a,[role=button],input[type=button],input[type=submit]';
  const SKIP = new Set(['STYLE', 'SCRIPT', 'LINK', 'NOSCRIPT', 'TEMPLATE']);
  const roots = [[document, false]];
  for (let i = 0; i < roots.length; i++) {
    roots[i][0].querySelectorAll('*').forEach(e => {
      if (e.shadowRoot) roots.push([e.shadowRoot, true]);
    });
  }
  const query = sel => {
    const out = [];
    for (const [r, inShadow] of roots) {
      try { r.querySelectorAll(sel).forEach(e => out.push([e, inShadow])); } catch (err) {}
    }
    return out;
  };
  const up = e => e.parentElement || (e.getRootNode && e.getRootNode().host) || null;
  const effOpacity = e => {
    let o = 1;
    for (let c = e; c && c.nodeType === 1; c = up(c)) {
      o *= parseFloat(getComputedStyle(c).opacity || '1');
    }
    return Math.round(o * 1000) / 1000;
  };
  const rectOf = e => {
    const r = e.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
  };
  const inside = (e, containers) => {
    for (let c = e; c; c = up(c)) if (containers.has(c)) return true;
    return false;
  };
  const descendants = container => {
    const rs = [container];
    if (container.shadowRoot) rs.push(container.shadowRoot);
    const els = [];
    for (let i = 0; i < rs.length; i++) {
      rs[i].querySelectorAll('*').forEach(e => {
        els.push(e);
        if (e.shadowRoot) rs.push(e.shadowRoot);
      });
    }
    return els;
  };
  const deepText = e => {
    let t = (e.innerText || '').trim();
    if (!t && e.shadowRoot) {
      t = [...e.shadowRoot.querySelectorAll('*')]
        .filter(c => !SKIP.has(c.tagName) && c.children.length === 0)
        .map(c => (c.innerText || c.textContent || '').trim()).filter(Boolean).join('\n');
    }
    return t;
  };
  const labelOf = e => ((e.innerText || '').trim() || (e.textContent || '').trim() || e.value || '')
    .replace(/\s+/g, ' ').slice(0, 300);
  const controlsOf = (container, cmp) => {
    const all = descendants(container);
    const picked = all.filter(e => {
      if (SKIP.has(e.tagName)) return false;
      if (e.matches(CLICKABLE)) return true;
      const label = (e.innerText || '').trim();
      if (!label || label.length > cfg.maxLabelChars) return false;
      if (getComputedStyle(e).cursor !== 'pointer') return false;
      const parent = up(e);
      if (parent && getComputedStyle(parent).cursor === 'pointer') return false;
      return !e.querySelector(CLICKABLE);
    }).slice(0, 60);
    const vendor = new Map();
    if (cmp) {
      for (const role of ['reject', 'accept', 'settings']) {
        for (const sel of cmp[role + '_selectors'] || []) {
          all.forEach(e => {
            try { if (e.matches(sel) && !vendor.has(e)) vendor.set(e, role); } catch (err) {}
          });
        }
      }
      vendor.forEach((role, e) => { if (!picked.includes(e)) picked.push(e); });
    }
    return picked.map(e => {
      const cs = getComputedStyle(e);
      const role = vendor.get(e) || null;
      return [e, {
        tag: e.tagName.toLowerCase(), text: labelOf(e), aria_label: e.getAttribute('aria-label'),
        css_id: e.id || null, rect: rectOf(e), visibility: cs.visibility, opacity: effOpacity(e),
        display: cs.display, cursor: cs.cursor, vendor_role: role,
        vendor_rule: role ? 'cmp:' + cmp.id + ':' + role : null,
      }];
    });
  };
  const candidateOf = (el, rule, inShadow, cmp) => {
    const pairs = controlsOf(el, cmp);
    let rect = rectOf(el);
    const cs = getComputedStyle(el);
    if (rect[2] * rect[3] === 0) {
      // A host element with a 0x0 box (e.g. a shadow-DOM CMP): use its visible controls' union.
      const boxes = pairs.map(p => p[1].rect).filter(r => r[2] * r[3] > 0);
      if (boxes.length) {
        const x1 = Math.min(...boxes.map(r => r[0]));
        const y1 = Math.min(...boxes.map(r => r[1]));
        const x2 = Math.max(...boxes.map(r => r[0] + r[2]));
        const y2 = Math.max(...boxes.map(r => r[1] + r[3]));
        rect = [x1, y1, x2 - x1, y2 - y1];
      }
    }
    const visible = rect[2] * rect[3] > 0 && cs.visibility === 'visible'
      && effOpacity(el) > 0 && cs.display !== 'none';
    return [pairs.map(p => p[0]), {
      rule, in_shadow_dom: inShadow || !!el.shadowRoot, rect, visible,
      text: deepText(el).slice(0, 10000), controls: pairs.map(p => p[1]),
    }];
  };

  const cmpEvidence = {};
  const found = [];
  const cmpEls = new Set();
  const scriptHosts = new Set([...document.scripts].map(s => {
    try { return new URL(s.src).hostname; } catch (e) { return ''; }
  }));
  for (const cmp of cfg.cmps) {
    const ev = [];
    for (const g of cmp.globals || []) {
      try { if (window[g] !== undefined) ev.push('global:' + g); } catch (e) {}
    }
    for (const h of cmp.script_hosts || []) if (scriptHosts.has(h)) ev.push('script:' + h);
    for (const sel of cmp.banner_selectors || []) {
      const hits = query(sel);
      if (hits.length) ev.push('selector:' + sel);
      for (const [el, inShadow] of hits) {
        cmpEls.add(el);
        found.push(candidateOf(el, 'cmp:' + cmp.id, inShadow, cmp));
      }
    }
    cmpEvidence[cmp.id] = ev;
  }
  const keywords = cfg.keywords;
  let generic = 0;
  for (const [r, inShadow] of roots) {
    for (const el of r.querySelectorAll('*')) {
      if (generic >= cfg.maxCandidates) break;
      if (SKIP.has(el.tagName) || inside(el, cmpEls)) continue;
      const cs = getComputedStyle(el);
      const dialog = el.getAttribute('role') === 'dialog'
        || el.getAttribute('aria-modal') === 'true';
      if (!(cs.position === 'fixed' || cs.position === 'sticky' || dialog)) continue;
      const text = deepText(el);
      const low = text.toLowerCase(), lowTr = text.toLocaleLowerCase('tr');
      if (!keywords.some(k => low.includes(k) || lowTr.includes(k))) continue;
      found.push(candidateOf(el, 'generic:keywords', inShadow, null));
      generic++;
    }
  }
  return {
    data: {
      frame_url: location.href, cmp_evidence: cmpEvidence,
      tcf_api: typeof window.__tcfapi === 'function', candidates: found.map(f => f[1]),
    },
    elements: found.map(f => f[0]),
  };
}"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _ms_since(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


def _playwright_version() -> str | None:
    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return None


def _request_record(req: Any, t_ms: int, phase: str | None, main_frame: Any) -> dict[str, Any]:
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
        "t_ms": t_ms,
        "phase": phase,
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


def _scan_consent_ui(page: Any, cfg: dict[str, Any], t0: float) -> tuple[dict[str, Any], list]:
    """Read-only consent-UI scan of every frame -> (raw scan, element handles per frame).

    A frame that cannot be read (detached, navigating) is skipped; only a failure of the
    main frame is recorded as the scan's error.
    """
    from playwright.sync_api import Error as PlaywrightError

    consent_cfg = cfg.get("consent") or {}
    arg = {
        "cmps": consent_cfg.get("cmps") or [],
        "keywords": consent_cfg.get("banner_keywords") or [],
        "maxCandidates": int(consent_cfg.get("max_generic_candidates", 10)),
        "maxLabelChars": int(consent_cfg.get("max_label_chars", 80)),
    }
    frames: list[dict[str, Any]] = []
    handles: list[Any] = []
    error = None
    for frame in page.frames[: int(consent_cfg.get("max_frames_scanned", 30))]:
        try:
            result = frame.evaluate_handle(_CONSENT_JS, arg)
            frames.append(result.get_property("data").json_value())
            handles.append(result.get_property("elements"))
        except PlaywrightError as exc:
            if frame == page.main_frame:
                error = _short(exc)
    return {"scanned_at_ms": _ms_since(t0), "error": error, "frames": frames}, handles


def _snapshot(context: Any, page: Any, phase: str, t0: float) -> dict[str, Any]:
    storage, storage_error = _evaluate(page, _STORAGE_JS)
    return {
        "phase": phase,
        "at_ms": _ms_since(t0),
        "cookies": context.cookies(),
        "storage": storage if storage is not None else {"error": storage_error},
    }


def _navigation_error(exc: BaseException) -> dict[str, str]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    kind = "TimeoutError" if isinstance(exc, PlaywrightTimeoutError) else "Error"
    return {"type": kind, "message": str(exc)}


def _reject_flow(
    context: Any,
    page: Any,
    obs: dict[str, Any],
    phase: list[str | None],
    cfg: dict[str, Any],
    limiter: _RateLimiter,
    t0: float,
) -> None:
    """Rejected state after load: wait for a visible reject control, click it once,
    observe, reload the homepage once, observe, re-read the consent UI (K-16 addendum)."""
    from playwright.sync_api import Error as PlaywrightError

    consent_cfg = cfg.get("consent") or {}
    observe_ms = float(cfg.get("observe_seconds", 15.0)) * 1000
    nav_timeout_ms = float(cfg.get("navigation_timeout_seconds", 30.0)) * 1000
    deadline = time.monotonic() + float(consent_cfg.get("banner_wait_seconds", 15.0))
    poll_ms = float(consent_cfg.get("poll_interval_seconds", 1.0)) * 1000

    while True:
        raw, handles = _scan_consent_ui(page, cfg, t0)
        ui = assemble_consent_ui(raw, consent_cfg)
        result, index = plan_reject(ui, consent_cfg)
        if result == "click" or time.monotonic() >= deadline:
            break
        page.wait_for_timeout(poll_ms)

    obs["consent_ui_raw"] = raw
    obs["snapshots"].append(_snapshot(context, page, PHASE_BEFORE_ACTION, t0))
    action: dict[str, Any] = {
        "action": ROLE_REJECT,
        "result": result,
        "control_index": None,
        "clicked_at_ms": None,
        "navigated_after_click": None,
        "error": None,
    }
    obs["consent_action"] = action
    obs["reload"] = {
        "performed": False,
        "status": None,
        "final_url": None,
        "goto_ms": None,
        "error": None,
    }
    if result != "click":
        return

    banner = ui["banner"]
    action["control_index"] = index
    navigated: list[bool] = []
    page.on("framenavigated", lambda f: navigated.append(f == page.main_frame))
    try:
        element = (
            handles[banner["frame_index"]]
            .get_property(str(banner["candidate_index"]))
            .get_property(str(index))
            .as_element()
        )
        if element is None:
            raise PlaywrightError("chosen control is no longer attached")
        clicked_at = _ms_since(t0)
        phase[0] = PHASE_AFTER_ACTION
        element.click(timeout=float(consent_cfg.get("click_timeout_seconds", 5.0)) * 1000)
    except PlaywrightError as exc:
        phase[0] = PHASE_BEFORE_ACTION
        action["result"] = ACTION_CLICK_FAILED
        action["error"] = _short(exc)
        return

    action["result"] = ACTION_CLICKED
    action["clicked_at_ms"] = clicked_at
    obs["interactions"].append(
        {"action": "click", "role": ROLE_REJECT, "control_index": index, "t_ms": clicked_at}
    )
    page.wait_for_timeout(observe_ms)
    action["navigated_after_click"] = any(navigated)
    obs["snapshots"].append(_snapshot(context, page, PHASE_AFTER_ACTION, t0))

    phase[0] = PHASE_AFTER_RELOAD
    limiter.acquire()
    started = time.monotonic()
    obs["reload"]["performed"] = True
    try:
        response = page.reload(wait_until="domcontentloaded", timeout=nav_timeout_ms)
        obs["reload"]["goto_ms"] = _ms_since(started)
        obs["reload"]["status"] = response.status if response is not None else None
        obs["reload"]["final_url"] = page.url
    except PlaywrightError as exc:
        obs["reload"]["error"] = _navigation_error(exc)
        return
    page.wait_for_timeout(observe_ms)
    obs["snapshots"].append(_snapshot(context, page, PHASE_AFTER_RELOAD, t0))
    obs["consent_ui_after_reload_raw"], _ = _scan_consent_ui(page, cfg, t0)


def _observe_state(
    browser: Any,
    consent_state: str,
    start_url: str,
    user_agent: str,
    cfg: dict[str, Any],
    limiter: _RateLimiter,
) -> dict[str, Any]:
    """Visit ``start_url`` in a fresh context and capture a raw observation dict.

    Untouched: no click, no scroll, no input — navigation, a fixed wait, a read-only
    consent-UI scan. Rejected: see ``_reject_flow``.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    nav_timeout_ms = float(cfg.get("navigation_timeout_seconds", 30.0)) * 1000
    observe_s = float(cfg.get("observe_seconds", 15.0))
    budget_s = float(cfg.get("state_budget_seconds", 120.0))
    max_requests = int(cfg.get("max_requests", 1000))
    rejected = consent_state == CONSENT_REJECTED

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
        "consent_ui_raw": None,
    }
    if rejected:
        obs.update(
            consent_action={"action": ROLE_REJECT, "result": None},
            reload={"performed": False},
            consent_ui_after_reload_raw=None,
            snapshots=[],
        )
    captured: list[tuple[Any, int, str | None]] = []
    phase: list[str | None] = [PHASE_BEFORE_ACTION if rejected else None]
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
                captured.append((req, _ms_since(t0), phase[0]))

        page.on("request", _on_request)

        limiter.acquire()
        response = None
        try:
            response = page.goto(start_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
            obs["timing"]["goto_ms"] = _ms_since(t0)
        except PlaywrightError as exc:
            obs["navigation_error"] = _navigation_error(exc)

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
            if not rejected:
                page.wait_for_timeout(observe_s * 1000)  # fixed observation window, no input
            timing, _ = _evaluate(page, _TIMING_JS)
            obs["timing"]["dom_content_loaded_ms"] = (timing or {}).get("dcl")
            obs["timing"]["load_ms"] = (timing or {}).get("load")
            obs["final_url"] = page.url
            obs["title"], _ = _evaluate(page, "() => document.title")
            if rejected:
                _reject_flow(context, page, obs, phase, cfg, limiter, t0)
            else:
                obs["consent_ui_raw"], _ = _scan_consent_ui(page, cfg, t0)
            storage, storage_error = _evaluate(page, _STORAGE_JS)
            obs["storage"] = storage if storage is not None else {"error": storage_error}

        obs["cookies"] = context.cookies()
        obs["requests"] = [_request_record(r, t, p, page.main_frame) for r, t, p in captured]
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
    headless = bool(cfg.get("headless", False))

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
        browser = pw.chromium.launch(headless=headless, args=list(cfg.get("browser_args") or []))
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
                "args": list(cfg.get("browser_args") or []),
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
