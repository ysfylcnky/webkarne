"""Offline tests for the Bulgu #1 aggregation (karne.analyze.email_report).

A small database is seeded with real payload fixtures, scored via the rescore
layer, then the aggregation functions are checked against hand-counted values.
This guards against a silent aggregation bug feeding wrong figures into the thesis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karne import storage
from karne.analyze import email_report
from karne.analyze.rescore import rescore_scan
from karne.analyze.scoring import load_ruleset
from karne.models import Scan, ScanResult

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dns_email"

# (fixture, sector, expected grade) — grades verified in test_scoring.py.
SEED = [
    ("garantibbva_com_tr", "bank", "C"),
    ("akbank_com", "bank", "C"),
    ("istanbul_edu_tr", "university", "F"),
    ("mumifashion_com", "ecommerce", "F"),
    ("internet_nl", "unknown", "A"),
]
RUN = "2026-09"


def _payload(fixture: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{fixture}.json").read_text(encoding="utf-8"))


@pytest.fixture
def conn(tmp_path):
    connection = storage.connect(tmp_path / "karne.db")
    storage.init_db(connection)
    ruleset = load_ruleset()
    for i, (fixture, sector, _grade) in enumerate(SEED):
        dom = storage.get_or_create_domain(connection, f"d{i}.test", sector=sector)
        scan_id = storage.insert_scan(
            connection,
            Scan(domain_id=dom.id, scanner_version="test", status="ok", run_label=RUN),
        )
        storage.insert_scan_result(
            connection,
            ScanResult(scan_id=scan_id, collector="dns_email", payload=_payload(fixture)),
        )
        rescore_scan(connection, scan_id, ruleset)
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def test_overall_grades(conn):
    rows = email_report.scored_rows(conn, RUN)
    assert len(rows) == 5
    grades = email_report.overall_grades(rows)
    assert grades["C"] == 2  # both banks
    assert grades["F"] == 2  # istanbul + mumifashion
    assert grades["A"] == 1  # internet.nl


def test_sector_matrix(conn):
    rows = email_report.scored_rows(conn, RUN)
    matrix, totals = email_report.sector_grade_matrix(rows)
    assert totals["bank"] == 2
    assert matrix["bank"]["C"] == 2
    assert matrix["university"]["F"] == 1
    assert matrix["unknown"]["A"] == 1


def test_finding_prevalence_and_dmarc_posture(conn):
    prevalence = email_report.finding_prevalence(conn, RUN)
    # Four of the five lack DNSSEC; internet.nl has a DS record (no finding).
    assert prevalence["EMAIL_NO_DNSSEC"] == 4
    # istanbul + mumifashion are p=none; the three others enforce (p=reject).
    posture = email_report.dmarc_posture(prevalence, n_scored=5)
    assert posture["p_none"] == 2
    assert posture["enforce_reject"] == 3
    assert posture["no_record"] == 0


def test_report_renders_and_is_scoped_to_run(conn):
    report = email_report.build_report(conn, RUN)
    assert "Türkiye's email-security report card" in report
    assert "5 scored domains" in report or "5 scored" in report
    # An empty round renders a clear, non-crashing message.
    assert "no scored domains" in email_report.build_report(conn, "1999-01")
