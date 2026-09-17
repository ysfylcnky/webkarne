#!/usr/bin/env bash
# Update the running WebKarne from GitHub, with automatic rollback.
# Run on the server as the admin (sudo-capable) user:
#
#   sudo bash /home/webkarne/webkarne/deploy/deploy.sh
#
# Steps: fast-forward pull as `webkarne` -> uv sync (runtime deps only) ->
# restart -> health check on 127.0.0.1:8000. If the new version does not answer,
# the checkout is reset to the previous commit and restarted again.
set -euo pipefail

APP_USER=webkarne
APP_DIR=/home/webkarne/webkarne
HEALTH_URL=http://127.0.0.1:8000/tr/

as_app() { sudo -u "$APP_USER" -H bash -lc "cd '$APP_DIR' && $*"; }

healthy() {
  for _ in $(seq 1 20); do
    if curl -fsS -o /dev/null "$HEALTH_URL"; then return 0; fi
    sleep 1
  done
  return 1
}

prev=$(as_app "git rev-parse HEAD")
as_app "git pull --ff-only"
new=$(as_app "git rev-parse HEAD")
echo "deploy: $prev -> $new"

# --no-dev skips pytest/ruff; the 'analysis' group is not a default group, so
# matplotlib/pandas are never installed here (PLAN.md K-14).
as_app "uv sync --frozen --no-dev"
systemctl restart webkarne

if healthy; then
  echo "deploy: OK ($new)"
  exit 0
fi

echo "deploy: health check FAILED — rolling back to $prev" >&2
journalctl -u webkarne -n 30 --no-pager >&2 || true
as_app "git reset --hard '$prev' && uv sync --frozen --no-dev"
systemctl restart webkarne
if healthy; then
  echo "deploy: rolled back to $prev (running)" >&2
else
  echo "deploy: rollback ALSO unhealthy — check journalctl -u webkarne" >&2
fi
exit 1
