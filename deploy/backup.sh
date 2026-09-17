#!/usr/bin/env bash
# Daily consistent backup of the server DB (derived copy, PLAN.md K-14).
# Install as the webkarne user's cron (crontab -e as webkarne):
#
#   17 3 * * * /home/webkarne/webkarne/deploy/backup.sh >> /home/webkarne/webkarne/data/logs/backup.log 2>&1
#
# Keeps the newest $KEEP snapshots. Snapshots are copies, never the live DB.
set -euo pipefail

APP_DIR=/home/webkarne/webkarne
KEEP=14
DEST="$APP_DIR/data/backups"

mkdir -p "$DEST" "$APP_DIR/data/logs"
cd "$APP_DIR"
.venv/bin/python scripts/db_snapshot.py data/karne.db "$DEST/karne-$(date -u +%Y%m%dT%H%M%SZ).db"

ls -1t "$DEST"/karne-*.db | tail -n +$((KEEP + 1)) | xargs -r rm --
