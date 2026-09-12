"""Expected-output tests for the dimension-A (email) scoring engine.

Per CLAUDE.md ("expected output before code"): the grade and finding set of each
known domain are **hand-computed** from the frozen raw payload fixtures under
tests/fixtures/dns_email/ and asserted here. These fixtures are the real payloads
observed in the 2026-09 country-wide run, so a passing test proves the scorer
reproduces the hand-derived interpretation of real data.

Scoring is a pure, offline layer (karne.analyze.scoring). It only READS the raw
payload; it never touches scan_results (K-02). Rules come from config/scoring.toml
(K-03); the dimension-A model is unchanged since ruleset 1.1.0 (1.2.0 only adds
dimension B), so these grades are stable. See PLAN.md K-12 for the model and the
decisions behind it.

Hand computation (dimension-A model as of ruleset 1.1.0), for reference:

  All six domains have MX -> transport indicators (MTA-STS/TLS-RPT/DANE) apply,
  and no scored indicator is servfail/timeout -> measured_weight = 100, no "I".
  None has DNSSEC / DANE / CAA / MTA-STS / TLS-RPT -> those 40 points are all 0.
  So raw_score = DMARC(<=35) + SPF(<=25).

  SPF (term 18 / lookup 7): -all -> 18+7=25 ; ~all -> 9+7=16.
  DMARC (policy 25 / rua 5 / sp 5; reject=1.0 none=0.15):
    p=reject,sp=reject,rua       -> 25 + 5 + 5      = 35.00
    p=reject,sp=absent(->reject) -> 25 + 5 + 5      = 35.00
    p=reject,sp=none(<p),rua     -> 25 + 5 + 0.75   = 30.75  (+SUBDOMAIN_WEAK)
    p=none, sp=none, rua         -> 3.75 + 5 + 0.75 =  9.50  (+POLICY_NONE)
    p=none, no sp, no rua        -> 3.75 + 0 + 0.75 =  4.50  (+POLICY_NONE,+NO_RUA)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karne.analyze.scoring import load_ruleset, score

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dns_email"

# Findings every one of these six domains must carry: none has DNSSEC, DANE, CAA,
# MTA-STS or TLS-RPT (all real absences, all scored 0).
_MISSING_INFRA = {
    "EMAIL_NO_DNSSEC",
    "EMAIL_NO_DANE",
    "EMAIL_NO_CAA",
    "EMAIL_NO_MTA_STS",
    "EMAIL_NO_TLS_RPT",
}

# domain fixture -> (raw_score, grade, exact set of finding codes)
EXPECTED: dict[str, tuple[float, str, set[str]]] = {
    "akbank_com": (
        60.0,
        "C",
        _MISSING_INFRA | {"EMAIL_DKIM_NOT_OBSERVED"},
    ),
    "itu_edu_tr": (
        60.0,
        "C",
        _MISSING_INFRA | {"EMAIL_DKIM_FOUND", "EMAIL_DKIM_KEY_SHORT"},
    ),
    "garantibbva_com_tr": (
        60.0,
        "C",
        _MISSING_INFRA | {"EMAIL_DKIM_FOUND", "EMAIL_DKIM_KEY_SHORT"},
    ),
    "turkiye_gov_tr": (
        55.75,
        "C",
        _MISSING_INFRA | {"EMAIL_DMARC_SUBDOMAIN_WEAK", "EMAIL_DKIM_NOT_OBSERVED"},
    ),
    "istanbul_edu_tr": (
        25.5,
        "F",
        _MISSING_INFRA
        | {
            "EMAIL_SPF_SOFTFAIL",
            "EMAIL_DMARC_POLICY_NONE",
            "EMAIL_DKIM_FOUND",
            "EMAIL_DKIM_KEY_SHORT",
        },
    ),
    "mumifashion_com": (
        20.5,
        "F",
        _MISSING_INFRA
        | {
            "EMAIL_SPF_SOFTFAIL",
            "EMAIL_DMARC_POLICY_NONE",
            "EMAIL_DMARC_NO_RUA",
            "EMAIL_DKIM_NOT_OBSERVED",
        },
    ),
    # internet.nl (the external reference tool's own domain) is the case that
    # exercises the v1.1.0 softfail compensation: SPF ~all + DMARC p=reject, plus
    # full DNSSEC/DANE/CAA. Softfail near-full (0.9*18 + 7 = 23.2) + DMARC 35 +
    # DNSSEC 15 + DANE 8 + CAA 7 = 88.2 -> A. The softfail finding still fires
    # (flagged compensated); only MTA-STS/TLS-RPT are missing.
    "internet_nl": (
        88.2,
        "A",
        {
            "EMAIL_SPF_SOFTFAIL",
            "EMAIL_NO_MTA_STS",
            "EMAIL_NO_TLS_RPT",
            "EMAIL_DKIM_NOT_OBSERVED",
        },
    ),
}


def _load(fixture: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ruleset() -> dict:
    return load_ruleset()


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_known_domain_score(fixture: str, ruleset: dict) -> None:
    payload = _load(fixture)
    expected_raw, expected_grade, expected_codes = EXPECTED[fixture]

    result = score(payload, ruleset)

    assert result.raw_score == pytest.approx(expected_raw), fixture
    assert result.grade == expected_grade, fixture
    got = {f.code for f in result.findings}
    assert got == expected_codes, (
        f"{fixture}: missing={expected_codes - got} extra={got - expected_codes}"
    )


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_ruleset_version_is_stamped(fixture: str, ruleset: dict) -> None:
    result = score(_load(fixture), ruleset)
    assert result.ruleset_version == "1.2.0"
    assert result.dimension == "email"


def test_all_known_domains_are_fully_measured(ruleset: dict) -> None:
    # None of the known domains has a servfail/timeout on a scored indicator, and
    # all have MX, so the full 100 weight is applicable and measured (no "I", no
    # dropouts).
    for fixture in EXPECTED:
        result = score(_load(fixture), ruleset)
        assert result.applicable_weight == pytest.approx(100.0), fixture
        assert result.measured_weight == pytest.approx(100.0), fixture
        assert "EMAIL_INSUFFICIENT_DATA" not in {f.code for f in result.findings}


def test_softfail_compensated_when_dmarc_enforces(ruleset: dict) -> None:
    # internet.nl: SPF ~all but DMARC p=reject -> the softfail is compensated
    # (v1.1.0). The finding still fires, flagged as compensated in its evidence.
    result = score(_load("internet_nl"), ruleset)
    softfail = next(f for f in result.findings if f.code == "EMAIL_SPF_SOFTFAIL")
    assert softfail.evidence.get("dmarc_compensated") is True


def test_softfail_not_compensated_without_enforcement(ruleset: dict) -> None:
    # mumifashion.com: SPF ~all with DMARC p=none -> no compensation; the softfail
    # is penalised (half) and NOT flagged compensated.
    result = score(_load("mumifashion_com"), ruleset)
    softfail = next(f for f in result.findings if f.code == "EMAIL_SPF_SOFTFAIL")
    assert "dmarc_compensated" not in softfail.evidence


# ---------------------------------------------------------------------------
# Synthetic payloads for branches the real fixtures don't exercise:
# multiple records, not-applicable (no MX), could-not-measure, insufficient data.
# ---------------------------------------------------------------------------


def _section(status: str = "nxdomain", present: bool = False, **extra) -> dict:
    return {"present": present, "query": {"status": status}, **extra}


def _synthetic(**overrides) -> dict:
    """A full-shaped payload with everything absent; override per indicator."""
    payload = {
        "domain": "synthetic.test",
        "spf": _section(),
        "dmarc": _section(),
        "dnssec": {
            "ds_present": False,
            "resolver_authenticated": None,
            "query": {"status": "noanswer"},
        },
        "mx": _section("ok", present=True, records=[{}], providers=["other"]),
        "dane": {"present": False, "hosts": []},
        "mta_sts": {"dns": _section(), "policy": {}},
        "tls_rpt": _section(),
        "caa": _section(),
        "dkim": {
            "found_selectors": [],
            "selectors_tried": [1] * 16,
            "method": "selector_guessing",
            "attempts": [],
        },
    }
    payload.update(overrides)
    return payload


def test_multiple_dmarc_records_score_zero_and_do_not_crash(ruleset: dict) -> None:
    # More than one DMARC record: parsed is a LIST; receivers ignore all.
    payload = _synthetic(
        dmarc={
            "present": True,
            "multiple": True,
            "records": ["v=DMARC1; p=reject", "v=DMARC1; p=none"],
            "parsed": [{"p": "reject", "valid": True}, {"p": "none", "valid": True}],
            "query": {"status": "ok"},
        }
    )
    result = score(payload, ruleset)
    codes = {f.code for f in result.findings}
    assert "EMAIL_DMARC_MULTIPLE" in codes
    # DMARC earns nothing; SPF absent too -> raw_score 0, grade F (all measured).
    assert result.grade == "F"
    assert result.measured_weight == pytest.approx(100.0)


def test_no_mx_makes_transport_indicators_not_applicable(ruleset: dict) -> None:
    # No MX -> MTA-STS / TLS-RPT / DANE are not applicable (18 pts) and drop out
    # of the denominator; the domain is not penalised for them.
    payload = _synthetic(mx=_section("noanswer", present=False))
    result = score(payload, ruleset)
    codes = {f.code for f in result.findings}
    assert "EMAIL_NO_MX" in codes
    assert result.applicable_weight == pytest.approx(82.0)  # 100 - 8 - 6 - 4
    assert "EMAIL_NO_DANE" not in codes  # not applicable, not a finding
    assert "EMAIL_NO_MTA_STS" not in codes


def test_servfail_indicator_is_unmeasured_not_penalised(ruleset: dict) -> None:
    # DMARC servfail -> could not measure: dropped from the denominator (rule 6),
    # not scored as absent.
    payload = _synthetic(dmarc=_section("servfail", present=False))
    result = score(payload, ruleset)
    codes = {f.code for f in result.findings}
    assert "EMAIL_INDICATORS_UNMEASURED" in codes
    assert "EMAIL_NO_DMARC" not in codes
    assert result.applicable_weight == pytest.approx(100.0)
    assert result.measured_weight == pytest.approx(65.0)  # 100 - 35 (dmarc)


def test_insufficient_data_yields_grade_I(ruleset: dict) -> None:
    # Most of the applicable weight could not be measured -> grade "I".
    payload = _synthetic(
        spf=_section("servfail"),
        dmarc=_section("servfail"),
        dnssec={
            "ds_present": False,
            "resolver_authenticated": None,
            "query": {"status": "servfail"},
        },
        caa=_section("timeout"),
    )
    result = score(payload, ruleset)
    codes = {f.code for f in result.findings}
    assert result.grade == "I"
    assert "EMAIL_INSUFFICIENT_DATA" in codes
    # Only MTA-STS/TLS-RPT/DANE (18) remained measurable of 100 applicable.
    assert result.measured_weight == pytest.approx(18.0)
