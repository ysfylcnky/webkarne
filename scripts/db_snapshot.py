"""Write a consistent snapshot of a live SQLite database (WAL-safe).

Copying karne.db with cp/scp while it is open can capture a torn file (the WAL
holds recent pages). SQLite's online backup API copies a consistent state instead.
Used to seed the server DB (PLAN.md K-14), for server backups, and at the end of a
monthly round. Never overwrites an existing file (rule 5 spirit: copies only add).

    uv run python scripts/db_snapshot.py data/karne.db data/snapshots/karne-2026-09-17.db
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def snapshot(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise SystemExit(f"source database not found: {src}")
    if dst.exists():
        raise SystemExit(f"refusing to overwrite existing file: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
        ok = target.execute("PRAGMA integrity_check;").fetchone()[0]
    finally:
        target.close()
        source.close()
    if ok != "ok":
        raise SystemExit(f"integrity check failed on {dst}: {ok}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    snapshot(src, dst)
    print(f"snapshot written: {dst} ({dst.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
