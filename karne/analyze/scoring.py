"""Dimension-A (email & domain identity) scoring — a pure, offline layer.

This module turns the RAW ``dns_email`` collector payload into a 0-100 score, a
letter grade, and a list of coded findings. It is the interpretation layer that
K-02 keeps strictly separate from collection: it only READS a payload dict and
never touches ``scan_results`` (persistence of the derived scores/findings lives
in ``karne.storage`` and is driven by ``karne rescore``).

Every threshold, weight and grade cut-off comes from ``config/scoring.toml``
(K-03); nothing is hard-coded here. The code decides which observation maps to
which finding code (logic); each code's ``severity`` and ``fix_hint_key`` are read
from the ruleset. Human-readable text lives in translation files (K-08), not here.

The scoring model and the decisions behind it (grade scale, weights, the
"could not measure" rule, DKIM as observation-only) are recorded in PLAN.md K-12.

Three distinct states are kept apart when interpreting an indicator (rule 6):

* **absent** — a real "no record" (``nxdomain`` / ``noanswer``): scored as 0.
* **not applicable** — the indicator cannot exist for this domain (e.g. mail
  transport indicators when there is no MX): excluded from the denominator, not a
  penalty and not "insufficient data".
* **could not measure** — a transient query failure (``servfail`` / ``timeout``):
  excluded from the denominator; if too much weight is unmeasured the grade
  becomes ``I`` (insufficient data). Never scored as an absence.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Query-result states that mean "could not measure" (rule 6): transient failures,
# kept distinct from a real absence (nxdomain / noanswer, handled via presence
# flags). An unmeasured indicator is dropped from the denominator, never scored 0.
_UNMEASURED_STATES = {"servfail", "timeout", "error"}

GRADE_INSUFFICIENT = "I"  # too much of the applicable surface could not be measured

_DEFAULT_RULESET_PATH = Path(__file__).resolve().parents[2] / "config" / "scoring.toml"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ScoreFinding:
    """One coded finding produced by scoring. ``severity`` and ``fix_hint_key``
    are looked up from the ruleset; ``evidence`` is machine-readable context."""

    code: str
    severity: str | None
    fix_hint_key: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreResult:
    """The derived interpretation of one dimension-A payload."""

    dimension: str
    ruleset_version: str
    raw_score: float | None
    grade: str
    findings: list[ScoreFinding]
    # Diagnostics (not persisted as columns, but useful for tests / evidence):
    applicable_weight: float  # scored weight that applies to this domain
    measured_weight: float  # applicable weight that could actually be measured
    earned: float  # points earned over measured indicators


# ---------------------------------------------------------------------------
# Ruleset loading
# ---------------------------------------------------------------------------


def load_ruleset(path: str | Path | None = None) -> dict[str, Any]:
    """Load and parse ``scoring.toml``. Defaults to the repo's config file."""
    p = Path(path) if path is not None else _DEFAULT_RULESET_PATH
    with p.open("rb") as fh:
        return tomllib.load(fh)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _query_status(section: Any) -> str | None:
    """Return the DNS query status of a payload section, if present."""
    if isinstance(section, dict):
        q = section.get("query")
        if isinstance(q, dict):
            return q.get("status")
    return None


def _grade_for(raw_score: float, grades: dict[str, Any]) -> str:
    """Map a 0-100 raw score to a letter using the ruleset cut-offs (>=)."""
    # Highest cut-off first: A, B, C, D, else F.
    for letter in ("A", "B", "C", "D"):
        cut = grades.get(letter)
        if cut is not None and raw_score >= cut:
            return letter
    return "F"


# ---------------------------------------------------------------------------
# Indicator scorers
#
# Each returns (weight, earned, measured, applicable, findings):
#   applicable=False  -> not applicable for this domain (drop from denominator)
#   measured=False    -> could not measure (drop from denominator; feeds "I")
#   earned in [0, weight] only when applicable and measured.
# ---------------------------------------------------------------------------


@dataclass
class _Part:
    weight: float
    earned: float
    measured: bool
    applicable: bool
    findings: list[ScoreFinding]


def _finding(code: str, ruleset: dict, evidence: dict | None = None) -> ScoreFinding:
    meta = ruleset.get("findings", {}).get(code, {})
    return ScoreFinding(
        code=code,
        severity=meta.get("severity"),
        fix_hint_key=meta.get("fix_hint_key"),
        evidence=evidence or {},
    )


def _score_spf(
    payload: dict, cfg: dict, weights: dict, ruleset: dict, dmarc_enforced: bool
) -> _Part:
    weight = float(weights["spf"])
    spf = payload.get("spf") or {}
    status = _query_status(spf)
    findings: list[ScoreFinding] = []

    if status in _UNMEASURED_STATES:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if not spf.get("present"):
        findings.append(_finding("EMAIL_NO_SPF", ruleset))
        return _Part(weight, 0.0, True, True, findings)

    if spf.get("multiple"):
        # More than one SPF record -> the record is invalid per RFC 7208.
        findings.append(_finding("EMAIL_SPF_MULTIPLE", ruleset))
        return _Part(weight, 0.0, True, True, findings)

    parsed = spf.get("parsed") or {}
    lookups = spf.get("lookups") or {}
    term_weight = float(cfg["terminator_weight"])
    lookup_weight = float(cfg["lookup_weight"])

    qualifier = (parsed.get("terminator") or {}).get("qualifier")
    frac_map = {
        "-": ("term_fail", None),
        "~": ("term_softfail", "EMAIL_SPF_SOFTFAIL"),
        "?": ("term_neutral", "EMAIL_SPF_NEUTRAL"),
        "+": ("term_pass", "EMAIL_SPF_PASS_ALL"),
    }
    key, finding_code = frac_map.get(qualifier, ("term_neutral", "EMAIL_SPF_NEUTRAL"))
    evidence = {"terminator": qualifier}
    if qualifier == "~" and dmarc_enforced:
        # DMARC enforcement (p=reject/quarantine) compensates an SPF softfail:
        # unaligned mail is rejected by DMARC regardless of the softfail. A small
        # edge is kept for a hard -all (defense in depth) via a near-full fraction
        # (ruleset 1.1.0; PLAN.md K-12). The finding is still emitted, flagged as
        # compensated, so the fix hint can still recommend tightening to -all.
        term_frac = float(cfg["term_softfail_dmarc_enforced"])
        evidence["dmarc_compensated"] = True
    else:
        term_frac = float(cfg[key])
    term_earned = term_frac * term_weight
    if finding_code:
        findings.append(_finding(finding_code, ruleset, evidence))

    if lookups.get("exceeds_limit"):
        lookup_earned = 0.0
        findings.append(
            _finding(
                "EMAIL_SPF_LOOKUP_LIMIT",
                ruleset,
                {"total_lookups": lookups.get("total_lookups"), "limit": lookups.get("limit")},
            )
        )
    else:
        lookup_earned = lookup_weight

    return _Part(weight, term_earned + lookup_earned, True, True, findings)


def _score_dmarc(payload: dict, cfg: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["dmarc"])
    dmarc = payload.get("dmarc") or {}
    status = _query_status(dmarc)
    findings: list[ScoreFinding] = []

    if status in _UNMEASURED_STATES:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if not dmarc.get("present"):
        findings.append(_finding("EMAIL_NO_DMARC", ruleset))
        return _Part(weight, 0.0, True, True, findings)

    if dmarc.get("multiple"):
        # More than one DMARC record -> receivers ignore all of them (RFC 7489),
        # so the domain has no effective DMARC. `parsed` is a list in this case.
        findings.append(
            _finding(
                "EMAIL_DMARC_MULTIPLE",
                ruleset,
                {"count": len(dmarc.get("records") or [])},
            )
        )
        return _Part(weight, 0.0, True, True, findings)

    parsed = dmarc.get("parsed")
    if not isinstance(parsed, dict) or not parsed.get("valid"):
        issues = parsed.get("issues") if isinstance(parsed, dict) else None
        findings.append(_finding("EMAIL_DMARC_INVALID", ruleset, {"issues": issues}))
        return _Part(weight, 0.0, True, True, findings)

    policy_weight = float(cfg["policy_weight"])
    rua_weight = float(cfg["rua_weight"])
    sp_weight = float(cfg["sp_weight"])

    policy_frac = {
        "reject": cfg["policy_reject"],
        "quarantine": cfg["policy_quarantine"],
        "none": cfg["policy_none"],
    }
    p = parsed.get("p")
    policy_earned = float(policy_frac.get(p, 0.0)) * policy_weight
    if p == "none":
        findings.append(_finding("EMAIL_DMARC_POLICY_NONE", ruleset))
    elif p == "quarantine":
        findings.append(_finding("EMAIL_DMARC_POLICY_QUARANTINE", ruleset))

    # Subdomain policy: sp= defaults to p= when absent.
    sp = parsed.get("sp") or p
    sp_frac = {
        "reject": cfg["sp_reject"],
        "quarantine": cfg["sp_quarantine"],
        "none": cfg["sp_none"],
    }
    sp_earned = float(sp_frac.get(sp, 0.0)) * sp_weight
    # Weaker subdomain policy than the domain policy is an explicit gap.
    _rank = {"none": 0, "quarantine": 1, "reject": 2}
    if parsed.get("sp") and _rank.get(sp, 0) < _rank.get(p, 0):
        findings.append(_finding("EMAIL_DMARC_SUBDOMAIN_WEAK", ruleset, {"p": p, "sp": sp}))

    # Aggregate reporting (rua). Absent -> no monitoring, the record is symbolic.
    if parsed.get("rua"):
        rua_earned = rua_weight
    else:
        rua_earned = 0.0
        findings.append(_finding("EMAIL_DMARC_NO_RUA", ruleset))

    # pct below 100 only applies the policy to a fraction of mail. None -> RFC
    # default of 100 (no finding). pct may arrive as a string in the raw payload.
    pct = parsed.get("pct")
    if pct is not None:
        try:
            pct_val = int(pct)
        except (TypeError, ValueError):
            pct_val = None
        if pct_val is not None and pct_val < int(cfg["pct_full"]):
            findings.append(_finding("EMAIL_DMARC_PCT_PARTIAL", ruleset, {"pct": pct_val}))

    return _Part(weight, policy_earned + sp_earned + rua_earned, True, True, findings)


def _score_dnssec(payload: dict, cfg: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["dnssec"])
    dnssec = payload.get("dnssec") or {}
    status = _query_status(dnssec)
    findings: list[ScoreFinding] = []

    if status in _UNMEASURED_STATES:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if not dnssec.get("ds_present"):
        findings.append(_finding("EMAIL_NO_DNSSEC", ruleset))
        return _Part(weight, 0.0, True, True, findings)

    if dnssec.get("resolver_authenticated"):
        return _Part(weight, float(cfg["ds_authenticated"]) * weight, True, True, findings)

    # DS delegated but the resolver did not set the AD flag.
    findings.append(_finding("EMAIL_DNSSEC_UNVALIDATED", ruleset))
    return _Part(weight, float(cfg["ds_unvalidated"]) * weight, True, True, findings)


def _has_mx(payload: dict) -> bool | None:
    """True/False if MX presence was measured; None if it could not be measured."""
    mx = payload.get("mx") or {}
    if _query_status(mx) in _UNMEASURED_STATES:
        return None
    return bool(mx.get("present"))


def _score_dane(
    payload: dict, cfg: dict, weights: dict, ruleset: dict, has_mx: bool | None
) -> _Part:
    weight = float(weights["dane"])
    findings: list[ScoreFinding] = []

    if has_mx is None:
        # Cannot judge transport security without knowing the MX set.
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    if has_mx is False:
        return _Part(weight, 0.0, measured=True, applicable=False, findings=findings)

    dane = payload.get("dane") or {}
    hosts = dane.get("hosts") or []
    # If every TLSA lookup could not be measured, treat DANE as unmeasured.
    host_statuses = [(h.get("query") or {}).get("status") for h in hosts if isinstance(h, dict)]
    if host_statuses and all(s in _UNMEASURED_STATES for s in host_statuses):
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if not dane.get("present"):
        findings.append(_finding("EMAIL_NO_DANE", ruleset))
        return _Part(weight, 0.0, True, True, findings)

    # TLSA present. Trustworthy only if the zone is DNSSEC-signed.
    dnssec_signed = bool((payload.get("dnssec") or {}).get("ds_present"))
    if dnssec_signed:
        return _Part(weight, float(cfg["present"]) * weight, True, True, findings)
    findings.append(_finding("EMAIL_DANE_WITHOUT_DNSSEC", ruleset))
    return _Part(weight, float(cfg["without_dnssec"]) * weight, True, True, findings)


def _score_mta_sts(
    payload: dict, cfg: dict, weights: dict, ruleset: dict, has_mx: bool | None
) -> _Part:
    weight = float(weights["mta_sts"])
    findings: list[ScoreFinding] = []

    if has_mx is None:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    if has_mx is False:
        return _Part(weight, 0.0, measured=True, applicable=False, findings=findings)

    mta = payload.get("mta_sts") or {}
    dns = mta.get("dns") or {}
    if _query_status(dns) in _UNMEASURED_STATES:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if not dns.get("present"):
        findings.append(_finding("EMAIL_NO_MTA_STS", ruleset))
        return _Part(weight, 0.0, True, True, findings)

    # TXT record present; grade on the fetched policy mode when available.
    policy = mta.get("policy") or {}
    mode = policy.get("mode")
    if mode == "enforce":
        earned = float(cfg["mode_enforce"]) * weight
    elif mode == "testing":
        earned = float(cfg["mode_testing"]) * weight
        findings.append(_finding("EMAIL_MTA_STS_TESTING", ruleset))
    else:
        earned = float(cfg["mode_unknown"]) * weight
    return _Part(weight, earned, True, True, findings)


def _score_tls_rpt(
    payload: dict, cfg: dict, weights: dict, ruleset: dict, has_mx: bool | None
) -> _Part:
    weight = float(weights["tls_rpt"])
    findings: list[ScoreFinding] = []

    if has_mx is None:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    if has_mx is False:
        return _Part(weight, 0.0, measured=True, applicable=False, findings=findings)

    tls_rpt = payload.get("tls_rpt") or {}
    if _query_status(tls_rpt) in _UNMEASURED_STATES:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if tls_rpt.get("present"):
        return _Part(weight, float(cfg["present"]) * weight, True, True, findings)
    findings.append(_finding("EMAIL_NO_TLS_RPT", ruleset))
    return _Part(weight, 0.0, True, True, findings)


def _score_caa(payload: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["caa"])
    caa = payload.get("caa") or {}
    findings: list[ScoreFinding] = []

    if _query_status(caa) in _UNMEASURED_STATES:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)

    if caa.get("present"):
        return _Part(weight, weight, True, True, findings)
    findings.append(_finding("EMAIL_NO_CAA", ruleset))
    return _Part(weight, 0.0, True, True, findings)


def _observe_mx(payload: dict, ruleset: dict, has_mx: bool | None) -> list[ScoreFinding]:
    """MX is not scored (informational); emit a finding only when truly absent."""
    if has_mx is False:
        return [_finding("EMAIL_NO_MX", ruleset)]
    return []


def _observe_dkim(payload: dict, cfg: dict, ruleset: dict) -> list[ScoreFinding]:
    """DKIM is NOT scored (PLAN.md K-12). Selector guessing means an empty result
    is not "no DKIM", so absence is recorded as an observation, never a penalty."""
    dkim = payload.get("dkim") or {}
    found = dkim.get("found_selectors") or []
    findings: list[ScoreFinding] = []

    if not found:
        findings.append(
            _finding(
                "EMAIL_DKIM_NOT_OBSERVED",
                ruleset,
                {
                    "method": dkim.get("method"),
                    "selectors_tried": len(dkim.get("selectors_tried") or []),
                },
            )
        )
        return findings

    # Collect key sizes of the selectors that were found.
    min_bits = int(cfg["min_key_bits"])
    key_bits: list[int] = []
    for attempt in dkim.get("attempts") or []:
        if attempt.get("present"):
            kb = (attempt.get("parsed") or {}).get("key_bits")
            if isinstance(kb, int):
                key_bits.append(kb)
    findings.append(
        _finding(
            "EMAIL_DKIM_FOUND",
            ruleset,
            {"selectors": found, "key_bits": key_bits},
        )
    )
    if key_bits and min(key_bits) < min_bits:
        findings.append(
            _finding(
                "EMAIL_DKIM_KEY_SHORT",
                ruleset,
                {"key_bits": key_bits, "min_key_bits": min_bits},
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _aggregate(
    dimension: str,
    named_parts: list[tuple[str, _Part]],
    extra_findings: list[ScoreFinding],
    ruleset: dict[str, Any],
    *,
    unmeasured_code: str,
    insufficient_code: str,
) -> ScoreResult:
    """Combine scored indicator parts into a ScoreResult (shared across dimensions).

    Handles the applicable / measured / earned bookkeeping, the normalised score,
    the grade cut-offs, and the "insufficient data" rule (rule 6). ``named_parts``
    pairs each part with a short name (for the unmeasured-indicator evidence);
    ``extra_findings`` are non-scored observations (e.g. DKIM)."""
    grades = ruleset["grades"]
    version = ruleset["version"]
    findings: list[ScoreFinding] = []
    applicable_weight = measured_weight = earned = 0.0
    unmeasured: list[str] = []

    for name, part in named_parts:
        findings.extend(part.findings)
        if not part.applicable:
            continue
        applicable_weight += part.weight
        if not part.measured:
            unmeasured.append(name)
            continue
        measured_weight += part.weight
        earned += part.earned

    findings.extend(extra_findings)
    if unmeasured:
        findings.append(_finding(unmeasured_code, ruleset, {"indicators": unmeasured}))

    ratio = float(ruleset["scoring"]["insufficient_data_ratio"])
    if measured_weight <= 0.0:
        findings.append(
            _finding(
                insufficient_code,
                ruleset,
                {"measured_weight": 0.0, "applicable_weight": applicable_weight},
            )
        )
        return ScoreResult(
            dimension, version, None, GRADE_INSUFFICIENT, findings, applicable_weight, 0.0, 0.0
        )

    raw_score = round(100.0 * earned / measured_weight, 2)
    if applicable_weight > 0 and (measured_weight / applicable_weight) < ratio:
        findings.append(
            _finding(
                insufficient_code,
                ruleset,
                {"measured_weight": measured_weight, "applicable_weight": applicable_weight},
            )
        )
        grade = GRADE_INSUFFICIENT
    else:
        grade = _grade_for(raw_score, grades)

    return ScoreResult(
        dimension, version, raw_score, grade, findings, applicable_weight, measured_weight, earned
    )


def score(payload: dict[str, Any], ruleset: dict[str, Any]) -> ScoreResult:
    """Score one raw ``dns_email`` payload against ``ruleset`` (parsed toml).

    Pure and offline: no network, no database, no mutation of ``payload``.
    """
    email = ruleset["dimensions"]["email"]
    weights = email["weights"]

    has_mx = _has_mx(payload)

    # Does DMARC actively enforce? Used to compensate an SPF softfail (ruleset
    # 1.1.0): with p=reject/quarantine, an SPF ~all no longer leaves a gap.
    _dm = payload.get("dmarc") or {}
    _dm_parsed = _dm.get("parsed")
    dmarc_enforced = bool(
        _dm.get("present")
        and not _dm.get("multiple")  # multiple records -> no effective DMARC
        and isinstance(_dm_parsed, dict)
        and _dm_parsed.get("valid")
        and _dm_parsed.get("p") in ("reject", "quarantine")
    )

    named_parts = [
        ("dmarc", _score_dmarc(payload, email["dmarc"], weights, ruleset)),
        ("spf", _score_spf(payload, email["spf"], weights, ruleset, dmarc_enforced)),
        ("dnssec", _score_dnssec(payload, email["dnssec"], weights, ruleset)),
        ("dane", _score_dane(payload, email["dane"], weights, ruleset, has_mx)),
        ("caa", _score_caa(payload, weights, ruleset)),
        ("mta_sts", _score_mta_sts(payload, email["mta_sts"], weights, ruleset, has_mx)),
        ("tls_rpt", _score_tls_rpt(payload, email["tls_rpt"], weights, ruleset, has_mx)),
    ]
    extra = [
        *_observe_mx(payload, ruleset, has_mx),
        *_observe_dkim(payload, email["dkim"], ruleset),
    ]
    return _aggregate(
        "email",
        named_parts,
        extra,
        ruleset,
        unmeasured_code="EMAIL_INDICATORS_UNMEASURED",
        insufficient_code="EMAIL_INSUFFICIENT_DATA",
    )


# ---------------------------------------------------------------------------
# Dimension B (transport & server security) scorers
# ---------------------------------------------------------------------------

_MODERN_TLS = {"TLSv1.2", "TLSv1.3"}
_LEGACY_TLS = {"TLSv1", "TLSv1.1"}


def _score_https_enforcement(payload: dict, cfg: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["https_enforcement"])
    http = payload.get("http") or {}
    findings: list[ScoreFinding] = []
    hops = http.get("chain") or []
    got_response = any(h.get("status") is not None for h in hops)
    if not got_response:  # never got an HTTP response -> could not measure
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    if not http.get("reached_https"):
        findings.append(
            _finding("TRANSPORT_NO_HTTPS", ruleset, {"final_url": http.get("final_url")})
        )
        return _Part(weight, 0.0, True, True, findings)
    if http.get("cleartext_after_https"):
        findings.append(_finding("TRANSPORT_CLEARTEXT_REDIRECT", ruleset))
        return _Part(weight, float(cfg["cleartext_fraction"]) * weight, True, True, findings)
    return _Part(weight, weight, True, True, findings)


def _score_tls(payload: dict, cfg: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["tls"])
    tv = payload.get("tls_versions") or {}
    findings: list[ScoreFinding] = []
    probed = tv.get("probed") or {}
    statuses = [v.get("status") for v in probed.values()]
    if statuses and all(s == "error" for s in statuses):  # all probes errored
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    supported = set(tv.get("supported") or [])
    modern = bool(supported & _MODERN_TLS)
    legacy = sorted(supported & _LEGACY_TLS)
    if not modern:
        findings.append(
            _finding("TRANSPORT_TLS_OUTDATED", ruleset, {"supported": sorted(supported)})
        )
        return _Part(weight, 0.0, True, True, findings)
    if legacy:
        findings.append(_finding("TRANSPORT_TLS_LEGACY", ruleset, {"legacy": legacy}))
        return _Part(weight, float(cfg["legacy_fraction"]) * weight, True, True, findings)
    return _Part(weight, weight, True, True, findings)


def _score_certificate(payload: dict, cfg: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["certificate"])
    cert = payload.get("certificate") or {}
    findings: list[ScoreFinding] = []
    verified = cert.get("verified")
    if verified is None:  # could not obtain the certificate (connection error)
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    if verified is False:
        findings.append(
            _finding("TRANSPORT_CERT_INVALID", ruleset, {"reason": cert.get("verify_error")})
        )
        return _Part(weight, 0.0, True, True, findings)
    days = cert.get("days_remaining")
    if isinstance(days, int) and days < int(cfg["expiry_warn_days"]):
        findings.append(_finding("TRANSPORT_CERT_EXPIRING", ruleset, {"days_remaining": days}))
    return _Part(weight, weight, True, True, findings)


def _score_hsts(payload: dict, cfg: dict, weights: dict, ruleset: dict, reachable: bool) -> _Part:
    weight = float(weights["hsts"])
    findings: list[ScoreFinding] = []
    if not reachable:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    hsts = (payload.get("homepage") or {}).get("hsts") or {}
    if not hsts.get("present"):
        findings.append(_finding("TRANSPORT_NO_HSTS", ruleset))
        return _Part(weight, 0.0, True, True, findings)
    max_age = hsts.get("max_age") or 0
    if max_age >= int(cfg["min_max_age"]):
        frac = float(cfg["base"])
    else:
        frac = float(cfg["short"])
        findings.append(_finding("TRANSPORT_HSTS_SHORT", ruleset, {"max_age": max_age}))
    if hsts.get("include_subdomains"):
        frac += float(cfg["include_subdomains"])
    else:
        findings.append(_finding("TRANSPORT_HSTS_NO_INCLUDESUBDOMAINS", ruleset))
    if hsts.get("preload"):
        frac += float(cfg["preload"])
    return _Part(weight, min(frac, 1.0) * weight, True, True, findings)


def _score_security_headers(
    payload: dict, cfg: dict, weights: dict, ruleset: dict, reachable: bool
) -> _Part:
    weight = float(weights["security_headers"])
    findings: list[ScoreFinding] = []
    if not reachable:
        return _Part(weight, 0.0, measured=False, applicable=True, findings=findings)
    present_headers = (payload.get("homepage") or {}).get("security_headers") or {}
    core = list(cfg["core"])
    present = [h for h in core if h in present_headers]
    missing = [h for h in core if h not in present_headers]
    if missing:
        findings.append(
            _finding(
                "TRANSPORT_MISSING_SECURITY_HEADERS",
                ruleset,
                {"missing": missing, "present": present},
            )
        )
    frac = len(present) / len(core) if core else 0.0
    return _Part(weight, frac * weight, True, True, findings)


def _score_security_txt(payload: dict, cfg: dict, weights: dict, ruleset: dict) -> _Part:
    weight = float(weights["security_txt"])
    findings: list[ScoreFinding] = []
    if (payload.get("security_txt") or {}).get("present"):
        return _Part(weight, float(cfg["present"]) * weight, True, True, findings)
    findings.append(_finding("TRANSPORT_NO_SECURITY_TXT", ruleset))
    return _Part(weight, 0.0, True, True, findings)


def score_transport(payload: dict[str, Any], ruleset: dict[str, Any]) -> ScoreResult:
    """Score one raw ``tls_http`` payload (dimension B). Pure and offline."""
    t = ruleset["dimensions"]["transport"]
    weights = t["weights"]
    reachable = bool((payload.get("homepage") or {}).get("reachable"))
    named_parts = [
        ("https_enforcement", _score_https_enforcement(payload, t["https"], weights, ruleset)),
        ("tls", _score_tls(payload, t["tls"], weights, ruleset)),
        ("certificate", _score_certificate(payload, t["certificate"], weights, ruleset)),
        ("hsts", _score_hsts(payload, t["hsts"], weights, ruleset, reachable)),
        (
            "security_headers",
            _score_security_headers(payload, t["security_headers"], weights, ruleset, reachable),
        ),
        ("security_txt", _score_security_txt(payload, t["security_txt"], weights, ruleset)),
    ]
    return _aggregate(
        "transport",
        named_parts,
        [],
        ruleset,
        unmeasured_code="TRANSPORT_INDICATORS_UNMEASURED",
        insufficient_code="TRANSPORT_INSUFFICIENT_DATA",
    )
