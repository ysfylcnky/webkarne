"""Expected-output tests for the dimension-B (transport) scoring engine.

Per CLAUDE.md ("expected output before code"): the grade and finding set of each
known domain are **hand-computed** from the frozen raw payload fixtures under
tests/fixtures/tls_http/ and asserted here. These fixtures are the real payloads
observed with the tls_http collector, so a passing test proves the scorer
reproduces the hand-derived interpretation of real data.

Scoring is a pure, offline layer (karne.analyze.scoring.score_transport). It only
READS the raw payload; it never touches scan_results (K-02). Rules come from
config/scoring.toml version 1.2.0 (K-03); see PLAN.md K-13 for the model.

Hand computation (ruleset 1.2.0). Scored weights: https 25 / tls 20 / cert 20 /
hsts 15 / headers 15 / security_txt 5 (sum 100). All seven domains serve a valid,
non-expiring cert over enforced HTTPS with modern TLS and no legacy version, so
https(25) + tls(20) + cert(20) = 65 for every one. What separates them is HSTS,
the four core security headers (equal 3.75 share each) and security.txt:

  HSTS (15): absent -> 0 (+NO_HSTS); present, adequate max-age, no
    includeSubDomains -> 0.6*15 = 9.0 (+HSTS_NO_INCLUDESUBDOMAINS);
    present + includeSubDomains -> (0.6+0.25)*15 = 12.75.
  headers (15): n of 4 present -> n/4 * 15 (+MISSING_SECURITY_HEADERS if n<4).
  security.txt (5): present -> 5 ; absent -> 0 (+NO_SECURITY_TXT).

    internet.nl : 65 + 9.0(hsts,no-incsub) + 15(4/4) + 5      = 94.00 -> A
    akbank      : 65 + 12.75(hsts+incsub)  + 3.75(1/4) +0(no txt)+..= 91.25 -> A
    itu         : 65 + 12.75(hsts+incsub)  + 6.0(2/4) + 0        = 89.00 -> A
    istanbul    : 65 + 9.0(hsts,no-incsub) + 3.75(1/4) + 5       = 82.75 -> B
    turkiye     : 65 + 0(no hsts)          + 11.25(3/4) + 5      = 81.25 -> B
    garanti     : 65 + 0(no hsts)          + 0(0/4) + 5          = 70.00 -> B
    mumi        : 65 + 0(no hsts)          + 3.75(1/4) + 0       = 68.75 -> C
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karne.analyze.scoring import load_ruleset, score_transport

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tls_http"

# domain fixture -> (raw_score, grade, exact set of finding codes)
EXPECTED: dict[str, tuple[float, str, set[str]]] = {
    "internet_nl": (
        94.00,
        "A",
        {"TRANSPORT_HSTS_NO_INCLUDESUBDOMAINS"},
    ),
    "akbank_com": (
        91.25,
        "A",
        {"TRANSPORT_MISSING_SECURITY_HEADERS", "TRANSPORT_NO_SECURITY_TXT"},
    ),
    "itu_edu_tr": (
        89.00,
        "A",
        {"TRANSPORT_MISSING_SECURITY_HEADERS", "TRANSPORT_NO_SECURITY_TXT"},
    ),
    "istanbul_edu_tr": (
        82.75,
        "B",
        {"TRANSPORT_HSTS_NO_INCLUDESUBDOMAINS", "TRANSPORT_MISSING_SECURITY_HEADERS"},
    ),
    "turkiye_gov_tr": (
        81.25,
        "B",
        {"TRANSPORT_NO_HSTS", "TRANSPORT_MISSING_SECURITY_HEADERS"},
    ),
    "garantibbva_com_tr": (
        70.00,
        "B",
        {"TRANSPORT_NO_HSTS", "TRANSPORT_MISSING_SECURITY_HEADERS"},
    ),
    "mumifashion_com": (
        68.75,
        "C",
        {
            "TRANSPORT_NO_HSTS",
            "TRANSPORT_MISSING_SECURITY_HEADERS",
            "TRANSPORT_NO_SECURITY_TXT",
        },
    ),
}


def _load(fixture: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ruleset() -> dict:
    return load_ruleset()


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_known_domain_transport_score(fixture: str, ruleset: dict) -> None:
    payload = _load(fixture)
    expected_raw, expected_grade, expected_codes = EXPECTED[fixture]

    result = score_transport(payload, ruleset)

    assert result.raw_score == pytest.approx(expected_raw), fixture
    assert result.grade == expected_grade, fixture
    got = {f.code for f in result.findings}
    assert got == expected_codes, (
        f"{fixture}: missing={expected_codes - got} extra={got - expected_codes}"
    )


@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_ruleset_version_and_dimension(fixture: str, ruleset: dict) -> None:
    result = score_transport(_load(fixture), ruleset)
    assert result.ruleset_version == "1.2.0"
    assert result.dimension == "transport"


def test_all_known_domains_fully_measured(ruleset: dict) -> None:
    # Every known domain served a homepage and completed the TLS/cert probes, so
    # the full 100 weight is applicable and measured (no "I", no dropouts).
    for fixture in EXPECTED:
        result = score_transport(_load(fixture), ruleset)
        assert result.applicable_weight == pytest.approx(100.0), fixture
        assert result.measured_weight == pytest.approx(100.0), fixture
        assert "TRANSPORT_INSUFFICIENT_DATA" not in {f.code for f in result.findings}


def test_unreachable_homepage_is_insufficient() -> None:
    # A domain that never returns an HTTP response and whose TLS/cert probes all
    # error out cannot be graded: measured_weight/applicable_weight < 0.5 -> "I"
    # (rule 6). Nothing is scored 0 for a control we could not observe.
    ruleset = load_ruleset()
    payload = {
        "http": {"chain": [{"status": None}], "reached_https": False},
        "tls_versions": {"probed": {"TLSv1.2": {"status": "error"}}},
        "certificate": {"verified": None},
        "homepage": {"reachable": False},
        "security_txt": {"present": False},
    }
    result = score_transport(payload, ruleset)
    codes = {f.code for f in result.findings}
    assert result.grade == "I", codes
    assert "TRANSPORT_INSUFFICIENT_DATA" in codes
