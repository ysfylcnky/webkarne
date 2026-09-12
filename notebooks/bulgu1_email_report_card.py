"""Bulgu #1 runner — generate Türkiye's email-security report card.

Thin, dependency-free wrapper over :mod:`karne.analyze.email_report`. Reads the
stored scoring layer for a scan round and writes a Markdown report.

Usage (from the repo root):

    uv run python notebooks/bulgu1_email_report_card.py               # latest round
    uv run python notebooks/bulgu1_email_report_card.py --run-label 2026-09
    uv run python notebooks/bulgu1_email_report_card.py --out somewhere.md

The report is written under ``data/`` by default, which is gitignored: the CODE is
open from day one, but the dataset (and figures derived from it) is released only
at thesis submission (PLAN.md K-10). Run ``karne rescore`` first so the round has
scores/findings to aggregate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script (python notebooks/…): make the repo root importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from karne import storage  # noqa: E402
from karne.analyze.email_report import build_report  # noqa: E402


def latest_run_label(conn) -> str | None:
    row = conn.execute(
        "SELECT s.run_label AS rl FROM scores sc "
        "JOIN scans s ON sc.scan_id = s.id "
        "WHERE s.run_label IS NOT NULL "
        "ORDER BY s.run_label DESC LIMIT 1;"
    ).fetchone()
    return row["rl"] if row else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Bulgu #1 email report card.")
    parser.add_argument("--db", default=str(storage.DEFAULT_DB_PATH), help="SQLite database path.")
    parser.add_argument("--run-label", default=None, help="Scan round (default: latest scored).")
    parser.add_argument("--out", default=None, help="Output path (default: data/reports/).")
    args = parser.parse_args(argv)

    conn = storage.connect(args.db)
    try:
        storage.init_db(conn)
        run_label = args.run_label or latest_run_label(conn)
        if run_label is None:
            print("No scored scan round found. Run `karne rescore` first.", file=sys.stderr)
            return 1

        report = build_report(conn, run_label)
    finally:
        conn.close()

    out = Path(args.out) if args.out else Path("data/reports") / f"bulgu1_{run_label}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    print(report)
    print(f"\n[written to {out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
