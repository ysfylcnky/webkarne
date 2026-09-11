"""Offline tests for the rescoring orchestrator (Sprint 3).

No network. Real dimension-A payload fixtures are seeded into a temp database as
``scan_results``; the tests exercise the raw -> derived flow: persistence of
``scores``/``findings``, reproducibility (re-running replaces, never appends, and
never touches raw data), dimension-scoped deletion, the selection modes
(scan id / run label / only-unscored), and the no-payload skip.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from karne import storage
from karne.analyze import rescore
from karne.analyze.scoring import load_ruleset
from karne.models import Finding, Scan, ScanResult, Score

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dns_email"


def _payload(fixture: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture}.json").read_text(encoding="utf-8"))


@pytest.fixture
def conn(tmp_path):
    connection = storage.connect(tmp_path / "karne.db")
    storage.init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="module")
def ruleset() -> dict:
    return load_ruleset()


def _seed_scan(
    conn, domain: str, fixture: str | None, *, run_label: str | None = None
) -> int:
    """Create a domain + scan; attach the fixture payload as a dns_email result.

    ``fixture=None`` seeds a scan with no raw payload (nothing to score).
    """
    dom = storage.get_or_create_domain(conn, domain, source="test")
    scan_id = storage.insert_scan(
        conn, Scan(domain_id=dom.id, scanner_version="test", status="ok", run_label=run_label)
    )
    if fixture is not None:
        storage.insert_scan_result(
            conn, ScanResult(scan_id=scan_id, collector="dns_email", payload=_payload(fixture))
        )
    return scan_id


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_rescore_scan_persists_score_and_findings(conn, ruleset):
    scan_id = _seed_scan(conn, "garantibbva.com.tr", "garantibbva_com_tr")

    result = rescore.rescore_scan(conn, scan_id, ruleset)
    conn.commit()

    assert result is not None
    scores = storage.get_scores(conn, scan_id)
    assert len(scores) == 1
    assert scores[0].dimension == "email"
    assert scores[0].grade == "C"
    assert scores[0].raw_score == pytest.approx(60.0)
    assert scores[0].ruleset_version == "1.1.0"

    findings = storage.get_findings(conn, scan_id)
    codes = {f.code for f in findings}
    assert "EMAIL_NO_DNSSEC" in codes
    assert "EMAIL_DKIM_KEY_SHORT" in codes
    # Every stored finding carries the ruleset's severity + fix_hint_key.
    by_code = {f.code: f for f in findings}
    assert by_code["EMAIL_NO_DNSSEC"].severity == "medium"
    assert by_code["EMAIL_NO_DNSSEC"].fix_hint_key == "email.no_dnssec"


def test_rescore_is_reproducible_and_replaces(conn, ruleset):
    # Same raw data + same ruleset run twice = identical single set of rows.
    scan_id = _seed_scan(conn, "mumifashion.com", "mumifashion_com")

    rescore.rescore_scan(conn, scan_id, ruleset)
    conn.commit()
    first_scores = storage.get_scores(conn, scan_id)
    first_findings = {f.code for f in storage.get_findings(conn, scan_id)}

    rescore.rescore_scan(conn, scan_id, ruleset)
    conn.commit()
    second_scores = storage.get_scores(conn, scan_id)
    second_findings = {f.code for f in storage.get_findings(conn, scan_id)}

    assert len(second_scores) == 1  # replaced, not appended
    assert first_scores[0].grade == second_scores[0].grade == "F"
    assert first_findings == second_findings


def test_rescore_with_newer_ruleset_restates_grade(conn, ruleset):
    # The same raw data re-graded with a changed ruleset (K-02): November's data,
    # May's rules. Here we drop the A cut-off so garantibbva's 60.0 becomes an A.
    scan_id = _seed_scan(conn, "garantibbva.com.tr", "garantibbva_com_tr")
    rescore.rescore_scan(conn, scan_id, ruleset)
    conn.commit()
    assert storage.get_scores(conn, scan_id)[0].grade == "C"

    tweaked = copy.deepcopy(ruleset)
    tweaked["version"] = "9.9.9-test"
    tweaked["grades"]["A"] = 55  # 60.0 now clears A

    rescore.rescore_scan(conn, scan_id, tweaked)
    conn.commit()
    scores = storage.get_scores(conn, scan_id)
    assert len(scores) == 1
    assert scores[0].grade == "A"
    assert scores[0].ruleset_version == "9.9.9-test"


# ---------------------------------------------------------------------------
# Raw data is never touched (rule 5 / K-02)
# ---------------------------------------------------------------------------


def test_rescore_never_mutates_raw(conn, ruleset):
    scan_id = _seed_scan(conn, "akbank.com", "akbank_com")
    before = storage.get_scan_result(conn, scan_id, "dns_email").payload

    rescore.rescore_scan(conn, scan_id, ruleset)
    rescore.rescore_scan(conn, scan_id, ruleset)  # twice
    conn.commit()

    after = storage.get_scan_result(conn, scan_id, "dns_email").payload
    assert after == before
    # exactly one raw row survives (no duplication)
    assert len(storage.get_scan_results(conn, scan_id)) == 1


def test_deletion_is_dimension_scoped(conn, ruleset):
    # A pre-existing non-email score and a non-EMAIL finding must survive an
    # email re-score (finding codes are dimension-prefixed).
    scan_id = _seed_scan(conn, "akbank.com", "akbank_com")
    storage.insert_score(
        conn, Score(scan_id=scan_id, dimension="transport", ruleset_version="x", grade="B")
    )
    storage.insert_finding(conn, Finding(scan_id=scan_id, code="TLS_LEGACY_VERSION"))
    conn.commit()

    rescore.rescore_scan(conn, scan_id, ruleset)
    conn.commit()

    dims = {s.dimension for s in storage.get_scores(conn, scan_id)}
    assert dims == {"transport", "email"}
    codes = {f.code for f in storage.get_findings(conn, scan_id)}
    assert "TLS_LEGACY_VERSION" in codes  # other dimension untouched
    assert any(c.startswith("EMAIL_") for c in codes)


# ---------------------------------------------------------------------------
# Selection modes
# ---------------------------------------------------------------------------


def test_select_and_rescore_by_run_label(conn, ruleset):
    _seed_scan(conn, "akbank.com", "akbank_com", run_label="2026-09")
    _seed_scan(conn, "itu.edu.tr", "itu_edu_tr", run_label="2026-09")
    _seed_scan(conn, "mumifashion.com", "mumifashion_com", run_label="2026-08")

    summary = rescore.select_and_rescore(conn, ruleset, run_label="2026-09")

    assert summary.scored == 2
    assert summary.grade_counts["C"] == 2  # akbank + itu both C
    # The 2026-08 scan was not selected -> no score.
    other = storage.get_domain(conn, "mumifashion.com")
    scan = storage.latest_scan_for_domain(conn, "mumifashion.com")
    assert other is not None and scan is not None
    assert storage.get_scores(conn, scan.id) == []


def test_only_unscored_skips_already_scored(conn, ruleset):
    sid_a = _seed_scan(conn, "akbank.com", "akbank_com", run_label="2026-09")
    _seed_scan(conn, "itu.edu.tr", "itu_edu_tr", run_label="2026-09")

    # Score akbank first.
    rescore.rescore_scan(conn, sid_a, ruleset)
    conn.commit()

    summary = rescore.select_and_rescore(
        conn, ruleset, run_label="2026-09", only_unscored=True
    )
    assert summary.scored == 1  # only itu remained unscored


def test_by_scan_id_takes_precedence(conn, ruleset):
    sid = _seed_scan(conn, "istanbul.edu.tr", "istanbul_edu_tr")
    _seed_scan(conn, "akbank.com", "akbank_com")

    summary = rescore.select_and_rescore(conn, ruleset, scan_id=sid)
    assert summary.scored == 1
    assert storage.get_scores(conn, sid)[0].grade == "F"


def test_scan_without_payload_is_skipped(conn, ruleset):
    sid = _seed_scan(conn, "example.com", None)  # scan row, no raw result

    summary = rescore.select_and_rescore(conn, ruleset, scan_id=sid)
    assert summary.scored == 0
    assert summary.skipped_no_payload == 1
    assert storage.get_scores(conn, sid) == []
