"""Rescoring orchestrator: raw ``scan_results`` -> derived ``scores``/``findings``.

This is the glue above the two layers it connects: the pure scorer
(:mod:`karne.analyze.scoring`) and the storage layer (:mod:`karne.storage`).
Neither of those imports the other; this module depends on both.

Design (PLAN.md K-02 / K-03, and the Sprint 3 brief):

* Scoring only READS ``scan_results`` and never mutates it (rule 5). ``scores`` and
  ``findings`` are DERIVED and fully reproducible from the raw payload plus a
  ruleset version, so re-scoring is safe: a scan's prior derived rows for the
  dimension are deleted and rewritten. Running ``rescore`` twice with the same
  ruleset yields identical rows; running it with a newer ruleset restates the
  grade against the same raw data (the November scan can be re-graded with May's
  rules).
* Each written ``scores`` row records the ``ruleset_version`` that produced it.
* One dimension at a time (``email`` = dimension A, ``transport`` = dimension B).
  Finding codes are dimension-prefixed (``EMAIL_`` / ``TRANSPORT_``), so a
  re-score of one dimension leaves other dimensions' derived rows untouched.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from karne import storage
from karne.analyze.scoring import ScoreResult, score, score_transport
from karne.models import Finding, Score

# Dimension -> the finding-code prefix its scorer emits (for scoped deletion).
_CODE_PREFIX = {"email": "EMAIL_", "transport": "TRANSPORT_"}
# Dimension -> the collector whose raw payload feeds it.
_COLLECTOR = {"email": "dns_email", "transport": "tls_http"}
# Dimension -> the pure scorer that turns its raw payload into a ScoreResult.
_SCORER: dict[str, Callable[[dict, dict], ScoreResult]] = {
    "email": score,
    "transport": score_transport,
}
# Dimensions this orchestrator can rescore (a scorer + collector + prefix each).
SUPPORTED_DIMENSIONS = frozenset(_SCORER)


def collector_for(dimension: str) -> str:
    """The collector whose raw payload feeds ``dimension`` (e.g. transport ->
    tls_http). Used to select the right scans to (re)score."""
    return _COLLECTOR[dimension]


@dataclass
class RescoreSummary:
    """Outcome of a rescoring run."""

    dimension: str
    ruleset_version: str
    total_selected: int = 0
    scored: int = 0
    skipped_no_payload: int = 0
    grade_counts: Counter[str] = field(default_factory=Counter)

    def summary_line(self) -> str:
        grades = " ".join(f"{g}={self.grade_counts[g]}" for g in sorted(self.grade_counts))
        return (
            f"Rescored dimension '{self.dimension}' with ruleset "
            f"{self.ruleset_version}: {self.scored}/{self.total_selected} scored"
            + (
                f", {self.skipped_no_payload} skipped (no raw payload)"
                if self.skipped_no_payload
                else ""
            )
            + (f" | grades: {grades}" if grades else "")
        )


def rescore_scan(
    conn: sqlite3.Connection,
    scan_id: int,
    ruleset: dict,
    *,
    dimension: str = "email",
) -> ScoreResult | None:
    """(Re)score one scan for one dimension and persist the derived rows.

    Returns the :class:`ScoreResult`, or ``None`` if the scan has no raw payload
    for this dimension's collector (nothing to score). Does not commit; the caller
    controls the transaction.
    """
    collector = _COLLECTOR[dimension]
    raw = storage.get_scan_result(conn, scan_id, collector)
    if raw is None:
        return None

    result = _SCORER[dimension](raw.payload, ruleset)

    # Reproducibility: drop this dimension's prior derived rows, then rewrite.
    storage.delete_scoring_for_dimension(conn, scan_id, dimension, _CODE_PREFIX[dimension])
    storage.insert_score(
        conn,
        Score(
            scan_id=scan_id,
            dimension=result.dimension,
            ruleset_version=result.ruleset_version,
            raw_score=result.raw_score,
            grade=result.grade,
        ),
    )
    for f in result.findings:
        storage.insert_finding(
            conn,
            Finding(
                scan_id=scan_id,
                code=f.code,
                severity=f.severity,
                evidence=f.evidence or None,
                fix_hint_key=f.fix_hint_key,
            ),
        )
    return result


def rescore_scans(
    conn: sqlite3.Connection,
    scan_ids: list[int],
    ruleset: dict,
    *,
    dimension: str = "email",
    commit_every: int = 1000,
    progress: Callable[[int, int], None] | None = None,
) -> RescoreSummary:
    """(Re)score many scans, committing periodically. Returns a summary."""
    summary = RescoreSummary(
        dimension=dimension,
        ruleset_version=str(ruleset.get("version")),
        total_selected=len(scan_ids),
    )
    for i, scan_id in enumerate(scan_ids, start=1):
        result = rescore_scan(conn, scan_id, ruleset, dimension=dimension)
        if result is None:
            summary.skipped_no_payload += 1
        else:
            summary.scored += 1
            summary.grade_counts[result.grade] += 1
        if commit_every and i % commit_every == 0:
            conn.commit()
        if progress is not None:
            progress(i, summary.total_selected)
    conn.commit()
    return summary


def select_and_rescore(
    conn: sqlite3.Connection,
    ruleset: dict,
    *,
    scan_id: int | None = None,
    run_label: str | None = None,
    only_unscored: bool = False,
    dimension: str = "email",
    commit_every: int = 1000,
    progress: Callable[[int, int], None] | None = None,
) -> RescoreSummary:
    """Resolve the target scans (one ``scan_id`` / a ``run_label`` / all unscored)
    and rescore them. ``scan_id`` takes precedence when given."""
    if scan_id is not None:
        scan_ids = [scan_id]
    else:
        scan_ids = storage.select_scans_for_scoring(
            conn,
            run_label=run_label,
            only_unscored=only_unscored,
            dimension=dimension,
            collector=_COLLECTOR[dimension],
        )
    return rescore_scans(
        conn,
        scan_ids,
        ruleset,
        dimension=dimension,
        commit_every=commit_every,
        progress=progress,
    )
