# Deploying WebKarne

Production layout (PLAN.md K-14): Ubuntu VPS, Cloudflare (proxied) → Caddy (TLS,
security headers, `security.txt`) → uvicorn on `127.0.0.1:8000` (one worker,
systemd) → SQLite at `/home/webkarne/webkarne/data/karne.db`.

- The **server DB is a writable, derived copy**: web queries append ad-hoc scans
  (`run_label` NULL). The thesis dataset stays canonical on the local machine.
- **Monthly rounds run locally** (`scripts/monthly_round.ps1`), never on the server.
- Nothing secret lives in the repo. No runtime environment variables are needed.

Placeholders: `ADMIN` = your sudo-capable SSH user, `VPS` = the server host/IP.

---

## 1. One-time server setup

All commands as `ADMIN` on the server unless stated.

```bash
# 1a. uv for the webkarne user (skip if `sudo -u webkarne -H bash -lc 'uv --version'` works)
sudo -u webkarne -H bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'

# 1b. Code
sudo -u webkarne -H bash -lc 'git clone https://github.com/ysfylcnky/webkarne.git ~/webkarne'
sudo -u webkarne -H bash -lc 'cd ~/webkarne && uv sync --frozen --no-dev'
sudo -u webkarne mkdir -p /home/webkarne/webkarne/data/logs
```

## 2. Seed the database (from the local machine)

A plain copy of an open SQLite file can be torn; take a consistent snapshot first.

```powershell
# Local (Windows, repo root)
uv run python scripts/db_snapshot.py data/karne.db data/snapshots/karne-seed.db
scp data/snapshots/karne-seed.db ADMIN@VPS:/tmp/karne-seed.db
```

```bash
# Server — only while the service is stopped / not yet installed
sudo install -o webkarne -g webkarne -m 640 /tmp/karne-seed.db /home/webkarne/webkarne/data/karne.db
rm /tmp/karne-seed.db
```

Do **not** re-seed over a server DB that already holds web queries — that would
discard them (rule 5). Back it up first (section 6) if a re-seed is ever needed.

## 3. systemd service

```bash
sudo cp /home/webkarne/webkarne/deploy/webkarne.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now webkarne
systemctl status webkarne --no-pager
curl -sI http://127.0.0.1:8000/tr/ | head -n 1     # expect 200
```

## 4. Caddy

Merge the `webkarne.com` / `www.webkarne.com` blocks of `deploy/Caddyfile` into
`/etc/caddy/Caddyfile` (keep any existing global options), then:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

The CSP allows only same-origin scripts/styles plus Google Fonts. The UI has no
inline script or style; if a future change adds one, the browser console shows a
CSP violation.

`preload` in HSTS is only a token; do **not** submit the domain to hstspreload.org
unless every subdomain will serve HTTPS permanently.

## 5. Cloudflare

- **SSL/TLS mode:** Full (strict).
- **Cache bypass** (Cache Rule): URI path matches `/*/git`, `/*/tara`, `/*/analiz/*`
  → Bypass cache. These pages are per-scan and dynamic.
- **Rate limiting** (WAF → Rate limiting rule): URI path matches `/*/git` or
  `/*/tara` → e.g. 5 requests / 1 minute per IP → Block for 10 minutes. The app has
  its own guard too (`[web]` in `config/settings.toml`: 10-minute rescan cooldown,
  4 concurrent live scans).
- **Email routing:** create `security@webkarne.com` (Email → Email Routing) so the
  `security.txt` contact works.

## 6. Backups

As `webkarne` (`sudo -u webkarne crontab -e`):

```
17 3 * * * /home/webkarne/webkarne/deploy/backup.sh >> /home/webkarne/webkarne/data/logs/backup.log 2>&1
```

Keeps the newest 14 consistent snapshots in `data/backups/`. Pull one home
occasionally: `scp ADMIN@VPS:/home/webkarne/webkarne/data/backups/<file> data/snapshots/`.

## 7. Verify after go-live

1. `journalctl -u webkarne -n 50 --no-pager` — no tracebacks.
2. `https://webkarne.com/tr/` loads; query a real domain → "measuring…" → report.
3. Browser console: no CSP violations. Print preview: nav hidden, accordions open.
4. `curl -s https://webkarne.com/.well-known/security.txt`.
5. Query `webkarne.com` in the tool itself and on internet.nl — HSTS, security
   headers and `security.txt` should now pass.

## 8. Updating

After pushing to `main`:

```bash
sudo bash /home/webkarne/webkarne/deploy/deploy.sh
```

Fast-forward pull → `uv sync --frozen --no-dev` → restart → health check; on
failure it resets to the previous commit and restarts (see the script).

## Troubleshooting

- **Caddy cannot get a certificate behind Cloudflare:** the ACME HTTP challenge
  must reach the origin on port 80. Temporarily set the DNS record to "DNS only"
  (grey cloud) for issuance, or use a Cloudflare Origin Certificate in Caddy.
- **`attempt to write a readonly database`:** the service can only write
  `data/` (`ReadWritePaths`); check `data/` and `karne.db*` are owned by `webkarne`.
