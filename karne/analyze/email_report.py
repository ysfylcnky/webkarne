"""Bulgu #1 — Türkiye's email-security report card.

Aggregates the DERIVED dimension-A ``scores``/``findings`` of one scan round into
the figures behind the thesis's first finding. Like all of :mod:`karne.analyze`,
this reads only stored data and never mutates it; it works off the scoring layer
(``scores``/``findings``), not the raw payloads, so it reflects a specific
``ruleset_version`` (recorded per score row, K-03).

Pure aggregation functions (testable against a small seeded database) are kept
separate from the Markdown rendering. ``build_report`` ties them together; the
runnable notebook (``notebooks/bulgu1_email_report_card.py``) is a thin wrapper.

Output is English (developer/researcher-facing, K-08); the Turkish thesis prose
cites these figures.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

# Grades in report order. "I" = insufficient data (too much could not be measured).
GRADE_ORDER = ("A", "B", "C", "D", "F", "I")

# DMARC-posture finding codes (mutually exclusive scorer paths within DMARC).
_DMARC_NO = "EMAIL_NO_DMARC"
_DMARC_NONE = "EMAIL_DMARC_POLICY_NONE"
_DMARC_QUAR = "EMAIL_DMARC_POLICY_QUARANTINE"
_DMARC_MULTI = "EMAIL_DMARC_MULTIPLE"
_DMARC_INVALID = "EMAIL_DMARC_INVALID"


def scored_rows(conn: sqlite3.Connection, run_label: str) -> list[sqlite3.Row]:
    """Every scored domain in ``run_label`` with its sector and grade (one row/domain)."""
    return conn.execute(
        "SELECT d.domain AS domain, COALESCE(d.sector, 'unknown') AS sector, "
        "       d.is_public_body AS is_public_body, sc.grade AS grade, "
        "       sc.raw_score AS raw_score, sc.ruleset_version AS ruleset_version "
        "FROM scores sc "
        "JOIN scans s ON sc.scan_id = s.id "
        "JOIN domains d ON s.domain_id = d.id "
        "WHERE sc.dimension = 'email' AND s.run_label = ? "
        "ORDER BY d.domain;",
        (run_label,),
    ).fetchall()


def overall_grades(rows: list[sqlite3.Row]) -> Counter[str]:
    return Counter(r["grade"] for r in rows)


def sector_grade_matrix(
    rows: list[sqlite3.Row],
) -> tuple[dict[str, Counter[str]], Counter[str]]:
    """(sector -> grade Counter, sector -> total)."""
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    for r in rows:
        matrix[r["sector"]][r["grade"]] += 1
        totals[r["sector"]] += 1
    return dict(matrix), totals


def finding_prevalence(conn: sqlite3.Connection, run_label: str) -> dict[str, int]:
    """code -> number of DISTINCT domains in the round carrying that finding."""
    rows = conn.execute(
        "SELECT f.code AS code, COUNT(DISTINCT f.scan_id) AS n "
        "FROM findings f "
        "JOIN scans s ON f.scan_id = s.id "
        "WHERE s.run_label = ? "
        "GROUP BY f.code;",
        (run_label,),
    ).fetchall()
    return {r["code"]: r["n"] for r in rows}


def dmarc_posture(prevalence: dict[str, int], n_scored: int) -> dict[str, int]:
    """Split the scored domains by DMARC posture, derived from the finding codes.

    The DMARC scorer takes exactly one path per domain, so the problem codes are
    mutually exclusive; ``enforce`` (valid single ``p=reject``) is what remains.
    That remainder also absorbs the rare domains whose DMARC could not be measured
    (servfail/timeout) — a small over-count of ``enforce``, noted in the report.
    """
    no_dmarc = prevalence.get(_DMARC_NO, 0)
    p_none = prevalence.get(_DMARC_NONE, 0)
    p_quar = prevalence.get(_DMARC_QUAR, 0)
    broken = prevalence.get(_DMARC_MULTI, 0) + prevalence.get(_DMARC_INVALID, 0)
    enforce = n_scored - no_dmarc - p_none - p_quar - broken
    return {
        "no_record": no_dmarc,
        "p_none": p_none,
        "p_quarantine": p_quar,
        "multiple_or_invalid": broken,
        "enforce_reject": enforce,
    }


def _pct(n: int, total: int) -> str:
    return f"{(100 * n / total):.1f}%" if total else "0.0%"


def _grade_cells(counter: Counter[str]) -> str:
    return " | ".join(str(counter.get(g, 0)) for g in GRADE_ORDER)


def render_markdown(conn: sqlite3.Connection, run_label: str) -> str:
    rows = scored_rows(conn, run_label)
    n = len(rows)
    if n == 0:
        return f"# Bulgu #1 — no scored domains for run '{run_label}'.\n"

    ruleset_versions = sorted({r["ruleset_version"] for r in rows})
    grades = overall_grades(rows)
    matrix, totals = sector_grade_matrix(rows)
    prevalence = finding_prevalence(conn, run_label)
    dmarc = dmarc_posture(prevalence, n)

    lines: list[str] = []
    lines.append("# Bulgu #1 — Türkiye's email-security report card")
    lines.append("")
    lines.append(
        f"*Scan round `{run_label}` · dimension A (email & domain identity) · "
        f"ruleset {', '.join(ruleset_versions)} · {n:,} scored domains.*"
    )
    lines.append("")
    lines.append(
        "Derived from the stored scoring layer (`scores`/`findings`); the raw "
        "measurements are untouched (K-02). Grade `I` = insufficient data "
        "(too much of the applicable surface could not be measured — kept "
        "distinct from a real absence, rule 6)."
    )
    lines.append("")

    # --- Overall grades ---
    lines.append("## Overall grade distribution")
    lines.append("")
    lines.append("| Grade | Domains | Share |")
    lines.append("|---|---:|---:|")
    for g in GRADE_ORDER:
        lines.append(f"| {g} | {grades.get(g, 0):,} | {_pct(grades.get(g, 0), n)} |")
    lines.append("")
    passed = grades.get("A", 0) + grades.get("B", 0) + grades.get("C", 0)
    lines.append(
        f"**{_pct(passed, n)}** reach A–C; **{_pct(grades.get('F', 0), n)}** "
        f"score F. Strong postures (A/B) are rare: {grades.get('A', 0)} A, "
        f"{grades.get('B', 0)} B."
    )
    lines.append("")

    # --- By sector ---
    lines.append("## By sector")
    lines.append("")
    lines.append(
        "Sorted by the share reaching A–C. `is_public_body` is a "
        "TLD/seed-criterion signal, not a legal determination (Sprint 1)."
    )
    lines.append("")
    lines.append("| Sector | n | " + " | ".join(GRADE_ORDER) + " | A–C |")
    lines.append("|---|---:|" + "---:|" * len(GRADE_ORDER) + "---:|")
    ranked = sorted(
        totals,
        key=lambda s: (
            (matrix[s].get("A", 0) + matrix[s].get("B", 0) + matrix[s].get("C", 0)) / totals[s]
        ),
        reverse=True,
    )
    for sec in ranked:
        cc = matrix[sec]
        abc = cc.get("A", 0) + cc.get("B", 0) + cc.get("C", 0)
        lines.append(f"| {sec} | {totals[sec]:,} | {_grade_cells(cc)} | {_pct(abc, totals[sec])} |")
    lines.append("")

    # --- DMARC posture ---
    lines.append("## DMARC posture (the single strongest indicator)")
    lines.append("")
    lines.append("| Posture | Domains | Share |")
    lines.append("|---|---:|---:|")
    dmarc_labels = [
        ("No DMARC record", "no_record"),
        ("`p=none` (monitor only)", "p_none"),
        ("`p=quarantine`", "p_quarantine"),
        ("`p=reject` (enforcing)", "enforce_reject"),
        ("multiple / invalid", "multiple_or_invalid"),
    ]
    for label, key in dmarc_labels:
        cnt = dmarc[key]
        lines.append(f"| {label} | {cnt:,} | {_pct(cnt, n)} |")
    lines.append("")
    lines.append(
        "*(`p=reject` absorbs the few domains whose DMARC could not be "
        "measured — a small over-count.)*"
    )
    lines.append("")

    # --- Finding prevalence ---
    lines.append("## Finding prevalence")
    lines.append("")
    lines.append(
        "Share of scored domains carrying each finding (most common first). "
        "DKIM codes are observation-only (selector guessing; not scored)."
    )
    lines.append("")
    lines.append("| Finding | Domains | Share |")
    lines.append("|---|---:|---:|")
    for code, cnt in sorted(prevalence.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{code}` | {cnt:,} | {_pct(cnt, n)} |")
    lines.append("")

    # --- Measurement quality ---
    insufficient = prevalence.get("EMAIL_INSUFFICIENT_DATA", 0)
    unmeasured = prevalence.get("EMAIL_INDICATORS_UNMEASURED", 0)
    lines.append("## Measurement quality (rule 6)")
    lines.append("")
    lines.append(
        f"- Insufficient data (grade `I`): **{insufficient:,}** "
        f"({_pct(insufficient, n)}) — left ungraded, not mislabelled as absent."
    )
    lines.append(
        f"- At least one indicator could not be measured: **{unmeasured:,}** "
        f"({_pct(unmeasured, n)})."
    )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Generated by `karne/analyze/email_report.py`. Figures are derived "
        "and reproducible: re-running `karne rescore` then this report "
        "against the same raw data and ruleset yields the same numbers.*"
    )
    lines.append("")
    return "\n".join(lines)


def build_report(conn: sqlite3.Connection, run_label: str) -> str:
    """Public entry point: the full Markdown report for one scan round."""
    return render_markdown(conn, run_label)
