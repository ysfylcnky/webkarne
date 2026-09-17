# PROGRESS — Archive

Full historical session log of the project. The one-page current state lives in
`docs/PROGRESS.md`; this file holds every session record in full (nothing removed,
summarised or shortened). **Newest session first.**

Each entry records: what was done, decisions made, known gaps, and the starting
point for the next session.

The three persistent-memory files are `docs/PLAN.md` (what/why), `CLAUDE.md` (how),
and `docs/PROGRESS.md` (current state — one page). This archive is the long tail.

---

## Sprint 4 · Session 2 — Consent-UI observation + the "rejected" state

Scope: consent banner observation (both states) and the `rejected` state.
`accepted`, pre-checked boxes and fingerprinting hooks are later sessions.

**Research before questions (no clicks):** a read-only probe of 40 Turkish homepages.
- CMPs: OneTrust (vodafone, hürriyet, milliyet, ntv, toyota, cnntürk, trendyol), Cookiebot
  (dr.com.tr), Didomi (decathlon), TCF API (sözcü, habertürk, mynet), the Turkish CMP
  **Efilli** (akbank, shadow DOM), and custom banners (yapıkredi, mediamarkt, ikea,
  vestel, lcw, getir) — so vendor selectors alone are not enough.
- **Headless was blocked on 12/40** (mostly large e-commerce); "new headless" changed
  nothing (UA still says HeadlessChrome). Headed Chromium, UA untouched, opened 7 of them
  (işbank, trendyol, n11, lcw, teknosa, getir, decathlon); an off-screen window with
  background throttling disabled behaves the same.
- Block pages can be 200 (işbank "İstek Engellendi", also seen mis-decoded) or Turkish
  (decathlon "Bir dakika lütfen...").

**Decisions (user-approved, PLAN.md K-16 addendum before code):** headed off-screen
Chromium; own config rule set (CMP signatures/selectors + TR/EN label regexes, no new
dependency); reject = first layer only, visible controls only, "only necessary" counts as
reject under its own rule id, vendor rule beats label rule; protocol = click once →
observe 15 s → reload homepage once → observe 15 s → re-read banner; requests carry
`t_ms` + phase, cookies/storage snapshotted per phase; extended block markers
(`titles_any_status`).

**Independent checks in the browser pane (no clicks) corrected three assumptions before
code:** akbank.com is not banner-less (Efilli renders in an open shadow root with clickable
`<div>`s, invisible to `document.body.innerText`); vodafone's "Reddet" is a custom inline
`a#rejectAllButton`, not OneTrust's standard button; dr.com.tr hides Cookiebot's Decline
(`visibility:hidden; opacity:0`).

**Code (`web_privacy` 0.2.0):** pure `normalize_label` (Turkish-aware), `classify_label`,
`is_visible`, `assemble_consent_ui` (banner choice: first visible CMP candidate, else the
smallest visible generic candidate holding a visible reject/accept control),
`plan_reject`, interaction guards (untouched: none; rejected: at most one reject click,
consistent with `consent_action.result`). I/O: one read-only JS scan per frame (open
shadow roots, geometry + computed style + effective opacity, element handles returned so
exactly the planned control is clicked), `_reject_flow`. CLI summary shows consent lines.

**Tests:** 271 offline (+39: rejected-state fixture pair, 19 observed labels, hidden vendor
control, Efilli shadow div, priorities, visibility cases, banner selection, guards). 9 live
tests green on the first run (webkarne no banner; vodafone, yapıkredi, akbank clicked →
reload 200 → no banner after reload; OptanonAlertBoxClosed after reject on vodafone).

**Found on a manual CLI run:** dr.com.tr's visible reject is the word "Reddet" inside the
banner prose (a clickable `<span>`); the collector clicked it (label rule) while recording
the hidden Cookiebot Decline, and the banner did not return after reload. My earlier
expectation that dr.com.tr would be `control_not_found` was wrong; the offline fixture
modelled on it stays valid (hidden vendor control is never clicked).

**Known gaps:** closed shadow roots and second-layer settings are not observed; a state
takes ~60–80 s; Cookiebot dialogs contribute many zero-size second-layer controls
(recorded, invisible); still blocked when headed: hepsiburada, pegasus, yemeksepeti,
arçelik, beko, THY.

**Next:** Sprint 4 · Session 3 — `accepted` state + pre-checked box observation.

---

## Sprint 4 · Session 1 — Dimension C collector skeleton + the "untouched" consent state

Scope: `karne/collectors/web_privacy.py` skeleton and ONE consent state (untouched).
Reject/accept clicks, banner detection, fingerprinting hooks, tracker matching and
policy texts are later sessions.

**Decisions (user-approved, recorded in PLAN.md K-16 before code):**
- **Playwright 1.63 (Apache-2.0)** in a non-default `privacy` uv group; never on the
  server; imported lazily (missing -> loud collector error, never an empty payload).
- **One scan, three states in the payload** (`states.untouched/rejected/accepted`, each
  its own fresh browser context); `scans.consent_state` stays NULL (§5 note).
  `models.CONSENT_NONE="none"` renamed to `CONSENT_UNTOUCHED="untouched"` (never stored).
- **Outcome states (rule 6):** loaded · http_error · blocked (only with an observed,
  config-listed marker, stored as evidence) · timeout · dns_error · navigation_error ·
  browser_error · not_run. Failed states still keep what was observed.
- **Recorded:** all cookies via the browser protocol incl. HttpOnly and partition key,
  never values; localStorage/sessionStorage key names + IndexedDB database names; every
  request with the **full URL** (cut at 2048, flagged), host, type, status/failure, body
  size, frame. **No** first/third-party split (analysis layer, vendored PSL snapshot
  later) and no tracker labels. Tracker dataset: decision deferred.
- **User-Agent:** Chromium's own UA + the WebKarne identity appended.
- **Local only:** `karne scan <d> --collectors privacy`; `batch` rejects it
  (`SINGLE_SCAN_ONLY`), the web query never sees it (not in `DEFAULT_COLLECTORS`).
- Settings in `[web_privacy]` (+ `.block_markers`): 30 s navigation timeout, 15 s
  observation window, 60 s state budget, 1 s between navigations, 1000 requests cap,
  tr-TR / Europe/Istanbul / 1366x768, headless.

**Code:** pure layer (`assemble_state`, `normalize_cookies`, `normalize_requests`,
`block_evidence`, `classify_outcome`, `compose_user_agent`, `privacy_status`) separated
from the Playwright I/O layer (`_observe_state` captures a plain observation dict).
Registry entry `privacy`, `resolve_batch_specs`, CLI summary block.

**Tests:** 232 offline (199 -> +33: hand-written observation -> expected-state fixture
pair, every outcome class, value-never-stored, truncation, untouched-has-no-interaction
guard, missing-Playwright, CLI store, batch rejection); also green without the privacy
group installed. 5 live-browser tests (`-m network`) green.

**Expected output before code paid off.** Expectations were hand-written from sources
independent of the collector (our templates/CSP; mumifashion.com HTML via curl). The
first live run failed on webkarne.com: an extra host `static.cloudflareinsights.com`.
Investigation: Cloudflare Web Analytics injects its beacon at the edge only for
`Accept: text/html` (curl sent `*/*`), and our CSP blocks it — the browser records
`failure="csp"`, nothing is sent. The collector was right; the expectation was corrected
with this evidence in the test docstring. mumifashion.com matched as written (7
`sbjs_*` JS cookies, WooCommerce scripts, Google Fonts, no GTM/Meta/TikTok).

**Observations about our own site (not acted on):** webkarne.com sends every visitor's
request to Google Fonts (fonts.googleapis.com/gstatic.com) — exactly the §3-C
"transfer abroad / Google Fonts" pattern; Cloudflare Web Analytics is enabled in the
dashboard but dead (blocked by our CSP).

**Known gaps / notes:**
- Headless UA says `HeadlessChrome/153…`; some sites may treat it as a bot. Not changed
  (no evasion, §4); a later decision (headed/new-headless) if block rates are high.
- Chromium resolves names with the system resolver, not the K-11 fixed resolvers.
- Storage keys are read from the top-level origin only (iframe storage not captured).
- The new `[web_privacy]` section changes `config_hash` for A/B scans too (next round
  is November, so rounds stay internally consistent).
- `web/reports.latest_scan_id` picks the newest scan regardless of collectors: a
  privacy-only local scan copied to the server DB would hide A/B for that domain.
  Filter before any future DB snapshot / before wiring C into the web.
- `playwright install` deleted the unrelated, unregistered `chromium-1228/1234` from
  `%LOCALAPPDATA%\ms-playwright` (other tools may re-download them).
- `uv sync --group privacy` alone uninstalls the analysis group; sync both.

**Next:** Sprint 4 · Session 2 — consent banner observation + the `rejected` state
(click the banner's own reject only; K-06/K-07).

---

## Sprint 3 · Session 4 — Open decisions closed + go-live on webkarne.com (SPRINT 3 COMPLETE)

Resumed after the previous session crashed (state reconstructed from its last
messages + PLAN/PROGRESS; repo matched: commit `3830068`). Closed every open decision
with the user, recorded them in PLAN.md **before** code, then deployed.

**Decisions (PLAN.md K-14, K-15, §4):**
- **Server DB = writable copy** of the local DB (consistent snapshot); the thesis
  dataset stays canonical locally.
- **Web queries stay out of the thesis.** They are ad-hoc (`run_label` NULL; new
  domains also `source="web"`). Thesis findings come only from local round scans.
- **Monthly rounds run locally, by hand** (`scripts/monthly_round.ps1`: dry-run →
  batch → rescore email+transport → snapshot, transcript in `data/logs/`). No
  scheduler: a sleeping PC silently skipping a month would damage the time series.
- **Abuse guard, two layers, no IP logging:** in-app (10-min rescan cooldown reusing
  the recent ad-hoc scan, same-domain in-flight coalescing, max 4 concurrent live
  scans → "busy" message; `[web]` in settings.toml; one uvicorn worker) + Cloudflare
  rate limit.
- **User-Agent:** `WebKarne/1.0 (+https://webkarne.com/tr/hakkinda; passive
  measurement)` from 2026-09-17 (earlier scans differ by `config_hash`).
- **No composite grade** until dimension F (April) — K-15.
- **matplotlib/pandas** added in a non-default `analysis` uv group (user-approved);
  never installed on the server.
- `docs/design-refs/` gitignored (large local PNGs).

**Code:**
- `query.run_live_scan` guard (`_Guard`, `web_limits`, `ScanBusy`);
  `storage.latest_adhoc_scan_since` (round scans never stand in for a web query).
- **Caught a go-live blocker:** the scanning screen's fetch was an inline `<script>`,
  which the production CSP (`script-src 'self'`) would block — the query would hang
  on "measuring…". Moved into `app.js`; the UI now has zero inline script/style.
- Home "busy" alert (tr/en keys, token-only CSS).

**Deployment kit:** `deploy/webkarne.service` (hardened, `ReadWritePaths=data`),
`deploy/Caddyfile` (HSTS, CSP, XFO, nosniff, Referrer/Permissions-Policy,
RFC 9116 `security.txt`, www→apex), `deploy/deploy.sh` (ff-pull → sync → restart →
health check → auto-rollback), `deploy/backup.sh` (daily, keep 14),
`scripts/db_snapshot.py` (SQLite online-backup API + integrity check, never
overwrites), `docs/DEPLOY.md`.

**Go-live (2026-09-17):**
- Code published: https://github.com/ysfylcnky/webkarne (secret scan of tree + full
  history before push: clean).
- VPS: Ubuntu 24.04, 4 vCPU / 6 GB, Caddy 2.11.4. uv installed for `webkarne`;
  clone + `uv sync --frozen --no-dev` (Python 3.12.3). DB snapshot (698.5 MB,
  SHA-256 matched after upload) placed at `data/karne.db`. Trial run: 9 pages 200,
  unknown page 404, no errors. Backup cron 03:17. User ran the sudo steps (systemd
  unit, Caddyfile swap with backup + validate).
- Cloudflare (user): SSL Full (strict), rate-limit rule on `/{tr,en}/{git,tara}`
  (verified: 5th request → 429), cache-bypass rule, Email Routing for
  `security@webkarne.com` (verified by the user). DMARC raised `p=none` →
  `p=reject; sp=reject` (domain sends no mail). DNSSEC and CAA were already present.
- **Self-measurement:** live scan of webkarne.com from the server (scan 29577, 3.8 s):
  email **A 88.2**, transport **A 100**. Remaining findings: SPF `~all` (compensated),
  no MTA-STS / TLS-RPT, DKIM selector not in the guess list (Cloudflare's `cf2024-1`).

**Also:** `2026-10` round email dimension scored (14,768 scans: A 2, B 71, C 752,
D 2,829, F 10,523, I 591) — closes a known gap.

**Mistakes caught:** overwrote `.gitattributes` without reading it (restored from git,
no change); a PowerShell 5.1 read/write mangled UTF-8 in `DEPLOY.md` (restored from git,
redone with the edit tool, never committed).

**Known gaps / next:** SSH key is passphrase-protected, so remote work needs the user to
load it into a time-limited agent socket; `webkarne` sudo needs a password (user runs
sudo steps). uvicorn access log records only Cloudflare edge IPs (no visitor IP).
Next: **Sprint 4 — dimension C (privacy/tracking, Playwright)**; adding Playwright
needs user approval.

**Verify:** `ruff check` clean, `pytest -m "not network"` 199 passed.

---

## Sprint 3 · Session 3 — Live web UI: query flow, real screens, sector, print (COMPLETE)

Turned the foundation into a working product: a typed domain/email runs a live
scan and returns a real report. Every screen is governed by `docs/DESIGN-SYSTEM.md`
and the `webkarne-ui` skill; no raw colour/space/size/duration lives outside
`tokens.css`; every user-facing string is a tr/en translation key (parity enforced
at startup). No new dependency, no build step, no framework — SSR Jinja2 + a single
vanilla `app.js`.

**What was built:**

1. **Read-only data layer — `karne/web/reports.py`.** `load_report`,
   `dimension_detail` (per-control state from raw payload: pass/fail/unmeasured/na +
   info), `finding_detail`, and `sector_comparison`. Never scores, never writes raw
   data (K-02/K-03, rule 5); reads a `mode=ro` connection.

2. **Query flow — `karne/web/query.py` + routes.** `/git` validates the typed
   domain/email then renders the "measuring…" screen (`scanning.html`); its JS
   fetches `/tara`, which runs a FRESH live scan (`run_live_scan`: batch.collect_bundle
   → store_bundle(source="web") → rescore email+transport) and returns the report URL;
   `<noscript>` meta-refresh drives the same route for JS-off. **Every query scans
   from scratch — a stored scan is never handed back.**

3. **Scoped results (user requirement).** An email query lands on the email dimension
   only; a domain query on a web-scoped overview (`?kapsam=web`) that excludes email
   and shows transport + privacy/tech ("ölçülmedi"). Never a mix, never email-first in
   a domain report. Scope also drives the left-nav dimension list.

4. **Real screens.** Overview (`overview.html`, honest partial-measurement count, no
   invented composite), dimension (`dimension.html`, accordion controls — each finding
   row carries its **severity** icon + pill so low never reads as red; rows match the
   rail's severity summary one-to-one, counted per issue-bearing control), full finding
   page (`finding_full.html`, sticky anchor strip + scroll-spy), home query panels.

5. **Sector comparison (§ 4.5) — `sector.html`.** Per dimension (no composite — that
   decision is still open), the domain's grade set against the REAL grade distribution
   of its labelled sector (latest scan per peer), rendered as a server-side **inline
   SVG histogram** (no chart library) with the domain's own bucket highlighted. Peers
   are aggregated, never named. Honest empty state when the domain has no labelled
   sector. Reachable at `/{lang}/analiz/{id}/sektor` (was 404).

6. **Static pages — `article.html`.** Methodology / About / Open Data as real bilingual
   content, plus an honest "in preparation" `sektor` landing, closing the four top-nav
   404s. One frame, prose from translation keys, sibling cross-links.

7. **JS — `app.js` (vanilla, defer).** Accordion (grid-rows 0fr→1fr), copy
   (clipboard + textarea fallback), toggle-all, deep-link (#hash), scroll-spy
   (IntersectionObserver), and `[data-print]` → `window.print()`.

8. **Print / PDF (§ 8).** `@media print` block: drops top band, sidebar nav, toolbars;
   flows content full width; forces every accordion open; `break-inside: avoid` on data
   groups. "Raporu İndir (PDF)" = the browser's own print-to-PDF over this stylesheet.

**Fixes made this session:**
- Scope query (`?kapsam=`) leaked into child URLs built by concatenating onto
  `overview_url`, corrupting finding links back to the full mixed overview. Added a
  query-free `nav.report_url` for all path concatenation (findings, breadcrumbs).
- Control rows showed a generic red alert for every finding regardless of severity, and
  the rail severity summary (all findings) disagreed with the rows (one per control).
  Rows now render severity icon + pill; the summary counts per issue-bearing control.
- `_fmt_score(None)` crashed the overview/dimension for an insufficient-data grade
  ("I", null score); it now returns None so the grade renders letter-only.
- `home.new_scan_note` reworded — every query now scans live (not just first-seen).

**Decisions / notes:**
- Domain query shows web dimensions only, email query email only (user decision).
- Privacy (03) / Tech (04) stay labelled "ölçülmedi" (user decision) — collectors are
  Sprint 4–5, not built.
- Composite/overall grade still deliberately absent (no rule in `scoring.toml`); sector
  comparison is per-dimension so it does not depend on that open decision.
- Sector histogram kept screen-specific (not added to the `/tr/stil` catalog).

**Known gaps / next session:** VPS deployment (webkarne.com + VPS + DNS already
provisioned) is Sprint 3's only remaining task, on the user's server. Then Sprint 4
(dimension C — privacy/tracking, Playwright). Term tooltips and a live progress bar
(§ 8.1) are not built; the scanning screen is an honest indeterminate indicator.

**Verify:** `ruff check` clean, `pytest -m "not network"` 192 passed. Screens checked
in the browser against real scans (istanbul.edu.tr 29563: email F / transport B, sector
university — email better than 32%, transport 87%).

---

## Sprint 3 · Session 2 — Web UI foundation (shell, i18n, component catalog) (COMPLETE)

Built the server-rendered web-UI skeleton. No real analysis screens, no charts,
no JavaScript, no deployment — those are later sessions. Everything is governed by
`docs/DESIGN-SYSTEM.md`; no raw colour/space/size/radius/duration lives outside
`karne/web/static/tokens.css`.

**Stack decision (user-approved):** FastAPI + Uvicorn + Jinja2 (PLAN.md Sprint 3's
choice — no plan deviation). Added via `uv add fastapi uvicorn jinja2`. Server-side
render only; SPA/build-step/Tailwind explicitly avoided.

**What was built (5 approved steps):**

1. **Base template + bands.** `karne/web/app.py` (FastAPI, static mount — tokens.css
   stays at `karne/web/static/tokens.css`), `templates/base.html` + `_header.html`
   (top band §3.3, nav order binding) + `_footer.html`. Jinja `StrictUndefined` so a
   missing key/var fails loudly. Fonts (Playfair Display, Public Sans, IBM Plex Mono,
   latin-ext) linked in head; **Turkish glyphs verified rendering in all three real
   faces** (ğĞşŞıİçÇöÖüÜ). Added token `--fs-wordmark`.
2. **i18n.** `i18n.py` with `get_translator` (missing key raises) + `verify_parity`
   (run at import — tr/en must share one key set, the "build-time" check for K-08).
   `translations/tr.json` + `en.json`. URL prefixes `tr|en` only (unknown → 404,
   `/favicon.ico` → 204). Language switcher swaps only the prefix, same page (§9);
   `hreflang` + `aria-current`.
3. **Analysis shell** `templates/shell.html` + `_analysis_nav.html` (§3.4 exact
   order). CSS grid-areas + `position: sticky`, four breakpoints verified by computed
   style: **xl ≥1440** `264 1fr 340` (nav+rail sticky) · **lg 1080–1439** `264 1fr`
   (nav sticky, rail below) · **md 720–1079** single-col stacked · **sm <720** compact
   header. Active item = 2px `--good` bar + `--surface`. Unmeasured dims (privacy,
   tech — no collector yet) shown muted `--ink-4`. Nav drawer toggle deferred (needs
   JS). Added cache-busting `?v=<mtime>` on static links (fixed a stale-CSS trap).
4. **Component catalog** `/tr/stil` · `/en/stil` (`templates/catalog.html` +
   `_macros.html`). All 13 required components in their states, **real webkarne.com
   data (scan 29545)**: grade display (A/B/C/D/F/I + real C 55.5 / C 65.0 / F 20.5
   from mumifashion 14783); dimension cards; 8 finding rows + 1 open (§4.4 order,
   markup only) faithfully matching reference 03, incl. mono box with the real DMARC
   record `v=DMARC1; p=none; rua=mailto:security@webkarne.com` (`p=none` in `--bad`);
   control rows (pass/fail) + status rows (unmeasured/na); severity pills; tint boxes;
   mono box + copy (button visual, no JS); rail card; buttons (primary/secondary/text
   × default/hover/focus/disabled/loading); stat tiles; breadcrumb. Added token
   `--grade-i` (= `--ink-3`, neutral — insufficient data is not a fail).
5. **Mountain illustration** `icons/_mountain.svg` — inline, thin single-colour,
   `non-scaling-stroke`; two sizes (`--nav` `--ink-4`, `--home` `--line-strong`).
   Wired into the nav; shown in catalog §14.

**Honesty / data-model notes (surfaced to user):**
- Values tagged "örnek/example" in the catalog: sector average/rank stat tiles
  (no sector scoring yet) and the per-finding point delta ("−15 puan"). Clearly
  labelled in-template + in the catalog data note.
- **Gap found:** the design's per-finding point delta ("−X puan") is **not in the
  data model** — `findings` has no delta column (code · severity · evidence ·
  fix_hint). Rendered the impact line qualitatively + delta as example. The scoring
  layer would need to emit per-finding contributions (not a UI task).

**Deliberate deferrals (all later sessions):** all real screens incl. the home page
with the query panels (ref-04) and the live domain-query flow; inline-SVG charts;
accordion/copy/tooltip/progress JavaScript; PDF/print; FastAPI DB-backed routes;
VPS deployment. The nav drawer toggle and the top-band scroll-hairline also need JS.

**Verification note:** browser screenshots go blank/time out when the desktop-app
window is backgrounded (the pane stops painting). Verified all components rendered
via DOM/computed-style and captured key sections (grade scale/colours, grade real,
finding rows + open expansion + mono highlight, control pass/fail, buttons, mountain,
mobile reflow) at native and 375px widths; shell four-breakpoint behaviour verified
by computed style in step 3.

**Files:** `karne/web/{app,i18n}.py`, `karne/web/templates/{base,_header,_footer,
shell,_analysis_nav,_shell_demo,catalog,_macros}.html` + `templates/icons/*.svg`,
`karne/web/translations/{tr,en}.json`, `karne/web/static/app.css`, tokens added to
`tokens.css`, `.claude/launch.json`. `_shell_demo.html` + `/kabuk` route are a
temporary step-3 preview (real values, remove with the real Overview screen).

**Next session:** real screens (start with Overview + the home page query panels as
markup), then the FastAPI DB-backed routes + domain-query flow. **Code uncommitted**
(user commits on request).

---

## Sprint 3 · Session 1 — A-dimension scoring engine (COMPLETE)

**Correction to the Sprint 2 record above:** the full country-wide run has since
been completed. `karne batch --dry-run` reports run label **`2026-09` with
14,767 / 14,767 domains done, all `ok`** (DB now ~299 MB). So dimension-A raw data
for the whole frame is present in `scans` + `scan_results` + `dns_records`, ready to
score. (Sprint 2 was validated on 18 bank domains and its work is **still
uncommitted** in the working tree — `karne/batch.py`, `tests/test_batch.py`, plus
modified storage/cli/dns_email/models/settings — to be committed with this sprint's
work.)

**Sprint goal (this session):** the **dimension-A scoring engine** — a versioned,
re-runnable layer that turns the stored `dns_email` raw payload into a 0–100 score,
a letter grade, and coded findings. Reads `scan_results`, never writes them (K-02).

### Step 1 — scoring decisions (asked & confirmed, then recorded) — DONE

Four method decisions were put to the user and confirmed, then written into
**PLAN.md as K-12** and into **`config/scoring.toml` (version `1.0.0`)** before any
scoring code:

- **Grade scale — security-calibrated:** A≥85, B≥70, C≥55, D≥40, F<40. Absolute and
  reproducible; chosen over the classic 90/80/70 so the (generally weak) Turkish
  sample is discriminated rather than collapsed into F.
- **Weights (authentication-weighted, sum 100):** DMARC 35 (policy 25 / rua 5 /
  sp 5), SPF 25 (terminator 18 / lookup 7), DNSSEC 15, DANE 8, CAA 7, MTA-STS 6,
  TLS-RPT 4. **DKIM and MX are NOT scored.**
- **DKIM — observation only (weight 0).** Selector guessing means 0/16 ≠ "no DKIM"
  (verified live: akbank.com and turkiye.gov.tr both returned 0/16, yet internet.nl
  sees their DKIM). Emits `EMAIL_DKIM_FOUND` / `EMAIL_DKIM_NOT_OBSERVED` /
  `EMAIL_DKIM_KEY_SHORT`; never a penalty.
- **"Could not measure" (servfail/timeout) is never penalised (rule 6).** The
  unmeasured indicator is dropped from the denominator; the score is normalised over
  the measured applicable weight. If measured/applicable < 0.5 the letter becomes
  **`I` (insufficient data)**. NXDOMAIN/noanswer = a real absence and IS scored —
  kept distinct. Also: indicators that need MX (MTA-STS/TLS-RPT/DANE) are
  **not-applicable** when there is no MX and are likewise excluded (distinct from
  unmeasured; does not trigger the `I` ratio).

Run-wide reality that shaped (c): across the core indicators the `2026-09` run has
**2,582 servfail + 363 timeout** ("could not measure"), and turkiye.gov.tr's Sprint-0
SERVFAIL is **gone** here (the fixed 1.1.1.1/8.8.8.8 resolvers cleared it — K-11).

### Extra decision this session — ruleset 1.1.0 (SPF softfail compensation)

The user compared Karne against internet.nl (internet.nl scores itself 100%,
webkarne.com 93%) and asked whether the model is too harsh. Analysis: mostly no —
we intentionally score policy *strength* (`p=none`, `~all`) where internet.nl checks
existence/validity, which is exactly Karne's stated value-add (PLAN dim-A rationale);
and scope differs (IPv6/STARTTLS excluded per K-07, CAA is internet.nl's website
test). Indicator-level we agree: internet.nl has DNSSEC+DANE+CAA, the Turkish
institutions do not. One genuine issue surfaced: SPF `~all` was penalised even when
DMARC enforces, which is a double-count (DMARC reject already rejects unaligned
mail). **Decision (confirmed): ruleset 1.1.0** — when DMARC `p=reject/quarantine`,
`~all` scores near-full (0.9) instead of 0.5; the finding still fires flagged
`dmarc_compensated`. Does not change the six Turkish grades; lifts internet.nl 81→88.2
(B→A). Recorded in PLAN.md K-12 changelog. (Also folded into 1.1.0: multiple-DMARC
records now score 0 with `EMAIL_DMARC_MULTIPLE`, found while running the full set.)

### What was done (Steps 2–5)

- **Step 2 — expected output first.** `tests/fixtures/dns_email/*.json` = 7 real
  frozen payloads (the 6 known domains + internet.nl). `tests/test_scoring.py`
  asserts hand-computed grade + finding set for each, plus synthetic-payload tests
  for the branches the fixtures don't hit (multiple records, no-MX → N/A,
  servfail → unmeasured, insufficient-data → grade `I`).
- **Step 3 — `karne/analyze/scoring.py`** (pure, offline): `load_ruleset()` +
  `score(payload, ruleset) -> ScoreResult(raw_score, grade, findings, applicable/
  measured weight)`. Reads only the payload; no DB, no network. Three states kept
  distinct: absent (0) / not-applicable (dropped) / could-not-measure (dropped, feeds
  `I`).
- **Step 4 — `karne rescore` CLI + `karne/analyze/rescore.py`** (orchestrator, mirrors
  `batch.py`). Modes: `--scan-id` / `--run-label` / all-unscored (`--only-unscored`),
  `--dry-run`, `--scoring`. Writes `scores`+`findings` with `ruleset_version`, deletes
  a scan's prior derived rows for the dimension first (reproducible; never appends).
  Two storage helpers: `select_scans_for_scoring`, `delete_scoring_for_dimension`
  (dimension-scoped by the `EMAIL_` code prefix). **Never touches `scan_results`.**
- **Step 5 — live validation.** Rescored the full **2026-09 run: 14,767/14,767 in
  ~21 s**. Stored grades of all known domains match the hand-computed values exactly
  (internet.nl A/88.2, akbank/itu/garanti/turkiye C, istanbul/mumifashion F). Running
  rescore twice is idempotent (14,767 scores + 107,772 findings, replaced not
  appended). internet.nl parity holds at the indicator level.

### Türkiye-wide dimension-A grade distribution (run 2026-09, ruleset 1.1.0)

**A=2 · B=71 · C=754 · D=2,825 · F=10,529 · I=586** (of 14,767). Headline (Bulgu #1
material): ~71% score F — most Turkish domains have no meaningful email-authentication
posture; DNSSEC is near-absent (only 60 domains had a DS record in the run). `I` = 586
(~4%) could not be adequately measured (servfail/timeout-heavy) and were correctly left
ungraded rather than mislabelled as absent (rule 6). The top of the table (2 A, 71 B)
is thin — strong postures are rare.

### Tests / lint

**152 offline pass** (was 119; +21 scoring, +9 rescore, +3 CLI), 3 network deselected,
ruff clean.

### Known gaps / next steps

- **Ad-hoc scans (run_label NULL) not scored by the run rescore.** webkarne.com and the
  Sprint-0 ad-hoc scans are unscored under 2026-09 (they are not in that round). Score
  them with `karne rescore` (default all-unscored) or by `--scan-id` when needed;
  webkarne.com scores C/55.5 (good infra, `p=none` + `~all`).
- **This is dimension A only.** Grades are the email dimension; the report card's other
  columns (B transport, C privacy, D tech) come in later sprints. No composite grade yet.
- **Fix-hint / finding text not written.** `fix_hint_key`s are emitted but the tr/en
  translation files do not exist yet (UI sprint). Codes + keys are stable now.
- **Analysis notebook (Bulgu #1) — BUILT this session** (see below).

### Bulgu #1 — Türkiye's email-security report card (BUILT)

Turned the scored round into the thesis's first finding, with no new dependency
(stdlib only). `karne/analyze/email_report.py` = pure aggregation over the derived
`scores`/`findings` (overall + by-sector grade matrix, DMARC posture, finding
prevalence, measurement-quality accounting) + Markdown rendering;
`notebooks/bulgu1_email_report_card.py` = thin runner. The generated report is
written under `data/` (gitignored) — code is open, the dataset stays closed until
submission (K-10). `tests/test_email_report.py` seeds a small scored DB and checks
the aggregation (guards against a silent wrong-number bug). **156 offline tests pass.**

**Headline figures (run 2026-09, ruleset 1.1.0, 14,767 domains):**
- **71.3% score F**, only **5.6% reach A–C**; A/B are rare (2 A, 71 B).
- **99.6% have no DNSSEC** (only ~60 signed); **93.6% no CAA**.
- **DMARC:** 51.0% no record, 18.8% `p=none`, 19.1% `p=quarantine`, **only 10.7%
  enforce `p=reject`**.
- **Sector gap:** banks 55.6% reach A–C, universities 18.1%, the general `.tr`
  mass ~5.0%. Banks clearly lead; the long tail is unprotected.
- **4.0% graded `I`** (insufficient data) — measured/absent/unmeasurable kept
  distinct (rule 6), not mislabelled.

### Dimension B (TLS/HTTP) collector — BUILT (not yet wired into scan/batch)

Started the next Sprint 3 module. Decisions confirmed and recorded in PLAN.md §4
("Sınır kararı: TLS sürüm keşfi — çoklu el sıkışma kabul edilir") before coding:
- **TLS versions:** a separate standard handshake per version (1.0–1.3) on 443 to
  detect legacy support (internet.nl-parity); negotiated cipher per version only
  (no full cipher sweep). Browser-equivalent, within K-07; distinct from STARTTLS.
- **Certificate:** verifying handshake for full fields; on verification failure,
  capture the reason (expired/self-signed/hostname) + cert presence via a
  non-verifying handshake. (Full field parse of *invalid* certs is a stdlib limit —
  would need `cryptography`; deferred, flagged.)
- **HTTPS enforcement:** follow the `http://` chain up to 10 hops, recording each
  hop's scheme/host/status; flag a cleartext-after-https downgrade and host change.

`karne/collectors/tls_http.py` (COLLECTOR_VERSION 0.1.0): pure parsers
(`parse_hsts`, `parse_csp`, `parse_set_cookie`, `parse_security_txt`,
`analyze_redirect_chain`, cert-field extraction) + a network layer with explicit
exception→state mapping (rule 6). Reuses `_RateLimiter`/`load_settings`/`config_hash`
from dns_email; **stdlib only** (`ssl` + `urllib`), no new dependency.
`config/settings.toml` gained a `[tls_http]` block. Records raw facts only — no
scoring/judgement (rule 1). `tests/test_tls_http.py` (12 offline parser tests,
hand-written expected output) + `tests/test_tls_http_network.py` (2 live). **168
offline pass.** Live-validated: internet.nl (TLS1.2/1.3, valid LE cert, HSTS+CSP+…,
security.txt) and akbank.com (TLS1.2/1.3, DigiCert EV, HSTS preload+includeSubDomains).

**Wiring — DONE (selectable collector set).** Decision (asked/confirmed): scan/batch
take `--collectors` (dimension keys `email`,`transport`; default **both**), storing one
`scan_results` row per collector under a single scan. `batch.py` gained a
`CollectorSpec`/`REGISTRY`, `collect_bundle`, `combine_status` (ok=all / partial=mix /
error=all, matching models.py), and `store_bundle` (one scans row, per-collector
scan_result + A's dns_records projection; a crashed collector contributes to
status/error but writes no scan_result — rule 6). `run_batch` keeps the legacy
single-collector path (16 batch tests untouched) and adds a multi path when
`collectors` is passed. CLI `scan`/`batch` got `--collectors`; scan prints an A summary
and a compact B summary. `REGISTRY` collect is lambda-wrapped so test monkeypatching
still works. **175 offline pass** (+7); live end-to-end verified: `karne scan internet.nl`
→ one scan, two scan_results (dns_email + tls_http), 21 dns_records, status ok.

### Dimension B (transport) scorer — BUILT (ruleset 1.2.0)

The report card's transport column. Model asked/confirmed against A's framework and
recorded in **PLAN.md K-13**; rules live in `config/scoring.toml` **1.2.0** (K-03).
- **`config/scoring.toml` 1.2.0:** `[dimensions.transport.*]` weights (HTTPS
  enforcement 25 / TLS 20 / certificate 20 / HSTS 15 / security headers 15 /
  security.txt 5, sum 100) + thresholds, and the 13-code `TRANSPORT_` finding
  catalogue with severities + `fix_hint_key`s. Purely additive; the A model and the
  six known-domain A grades are unchanged (1.2.0 only adds B).
- **`karne/analyze/scoring.py`:** refactored A and B to share one `_aggregate()`
  core (three-state: absent 0 / not-applicable dropped / could-not-measure dropped,
  grade `I` if measured < 50% of applicable, rule 6). Added `score_transport()` and
  its `_score_*` parts. Pure/offline, reads raw only (rule 1/K-02).
- **`karne/analyze/rescore.py`:** generalised to dispatch by dimension —
  `email`→`dns_email`/`EMAIL_`/`score`, `transport`→`tls_http`/`TRANSPORT_`/
  `score_transport`. Dimension-scoped deletion keeps rescoring per-dimension safe.
- **`karne/cli.py`:** `karne rescore --dimension transport` now valid; fixed the
  selection to join on the dimension's own collector (was hard-coded to `dns_email`).
- **Tests:** `tests/test_scoring_transport.py` — 7 real domains hand-computed and
  frozen (internet.nl 94.0 A, akbank 91.25 A, itu 89.0 A, istanbul 82.75 B, turkiye
  81.25 B, garanti 70.0 B, mumi 68.75 C) + version/dimension + insufficient-data.
  Updated the A version assertions (1.1.0→1.2.0) and the CLI dimension tests.
  **192 offline pass** (+17), 5 network deselected, ruff clean.

**Still NOT done for B (at the time of this record):** **applying B to the frame** — a
fresh batch round (e.g. `karne batch --run-label 2026-10 --collectors email,transport`),
longer than A-only; the existing 2026-09 round is A-only and its domains count as done,
so B needs a new label. Cookie/header capture is homepage Set-Cookie only (full cookie
inventory is dimension C, Sprint 4). Invalid-cert full field parse deferred (would need
`cryptography`). *(Update: the `2026-10` email+transport run and the transport rescore
were completed in the following session — see `docs/PROGRESS.md`.)*

### Next session starting point

Dimension A is complete end-to-end (scanned → scored 1.2.0 → Bulgu #1). Dimension B
is now **collector + scorer complete** (ruleset 1.2.0), wired into scan/batch/rescore,
but **not yet applied to the frame**. Most logical next steps: (1) **fresh batch round**
applying B (email+transport) to the frame under a new run-label, then
`karne rescore --dimension transport` → the Türkiye-wide transport grade distribution
(Bulgu #2 material); (2) **FastAPI + bilingual UI + VPS** to make it a live tool (needs
the tr/en translation files behind the finding `fix_hint_key`s — both EMAIL_ and now
TRANSPORT_); (3) charts for Bulgu #1 — would add matplotlib/pandas (a dependency
decision, ask first). Note: ad-hoc scans (run_label NULL, e.g. webkarne.com) are still
unscored; run `karne rescore` for them when needed. **Commit all Sprint 3 work at
Sprint 3 END** (per the user's instruction — not yet committed).

---

## Sprint 2 · Session 1 — batch scanning engine (COMPLETE)

**Sprint goal (engine part) reached:** `karne batch` applies dimension A to the
frame in parallel, rate-limited, resumably, and gently — writing each result
through the same raw-write contract as `karne scan`. This session built the engine
and validated it live on a small subset; the **full 14,766 run and the monthly
cron were intentionally NOT started** (left for a dedicated run, per the plan).

### Resolver decision (Step 1 — asked and confirmed, then coded → PLAN.md K-11)

Two open questions carried from Sprint 0/1 were closed and written into PLAN.md as
**K-11** before any code:

- **Fixed, DNSSEC-validating resolvers** `1.1.1.1` (primary) + `8.8.8.8` (backup),
  set in `config/settings.toml` (`resolvers`). Replaces the system resolver, which
  in Sprint 0 mis-reported the DNSSEC AD flag (internet.nl) and could mask records
  (turkiye.gov.tr). Project-wide (affects `scan` too); makes DNSSEC observation
  correct and the measurement reproducible.
- **SERVFAIL re-query policy:** on SERVFAIL, wait `retry_backoff_seconds` and
  re-query once; a persisting SERVFAIL is recorded with `requeried=true`, kept
  distinct from NXDOMAIN (rule 6). Independent of the existing timeout retries.

Implemented as a small, marked addition to `DnsClient.resolve()` + a new
`DnsQuery.requeried` field; **COLLECTOR_VERSION 0.2.0 → 0.3.0**. Single and batch
scans share one `DnsClient`, so both produce identical raw data.

### What was done (Steps 2–4)

- **`karne/batch.py`** (new orchestrator, not a collector):
  - **Scan round = `run_label`** (default current UTC month, e.g. `2026-11`; aligns
    with K-09). Stored on every `scans` row → longitudinal series is
    `GROUP BY run_label`; resume is unambiguous.
  - **Resume:** `select_domains_to_scan` returns frame domains without an ok/partial
    scan in this round; re-running the same label skips done domains. `store_scan`
    (shared write contract) + `store_error_scan` (collector crash → scan-level
    `error` row, no raw result, rule 6).
  - **Parallel + gentle:** network in worker threads (`ThreadPoolExecutor`,
    `[dns].concurrency`), **all DB writes on the main thread** (one connection,
    serialized — stdlib sqlite3 stays single-threaded). Per-domain pacing via the
    collector's own rate limiter. A per-domain crash does not stop the run.
  - **Progress/summary:** periodic `[n/N] ok/partial/error/remaining` + a final
    summary (completed/scope, skipped, first 20 failures).
- **`karne/cli.py`:** new `karne batch` command (`--run-label`, `--sector`,
  `--limit`, `--concurrency`, `--db`, `--settings`); progress to stderr with an
  adaptive cadence. `scan`'s `_store`/`_scan_status` now delegate to `batch` so the
  two paths write identically.
- **`karne/storage.py`:** schema **v1 → v2** (`scans.run_label` + index) via an
  additive, idempotent `_migrate` (`ALTER TABLE ADD COLUMN` on old DBs). New read
  helpers: `select_domains_to_scan`, `count_done_domains`, `count_domains`,
  `run_status_counts`. `models.Scan.run_label` added. No refactor of existing code.
- **Tests:** `tests/test_batch.py` (16 offline) — resume (skip-done, error re-scanned,
  per-label selection), sector/limit filters, end-to-end raw writes, partial/crash
  paths, **concurrency actually capped** (max active ≤ limit), **deterministic
  rate-limiter** (fake clock). Plus 4 SERVFAIL-requery tests in `test_dns_email.py`.
  **117 offline pass** (was 97), 3 network deselected, ruff clean.

### Live validation (Step 4)

Migration verified on a copy of the real `data/karne.db`: 11 existing scans + 14,767
domains preserved, `run_label` column/index added, idempotent, schema history v1+v2.

Ran `karne batch --sector bank --limit 20` (18 bank domains, label `2026-09` =
current month). Result: **18/18 ok**, 0 partial, 0 error; every scan has a
`scan_results` row; **305 `dns_records`** rows written. Raw payloads confirm the
resolver set used was exactly **(1.1.1.1, 8.8.8.8)**, and the SERVFAIL policy fired
live (**6 re-queries; 4 persisted as `servfail`**, kept distinct — rule 6).
Re-running the same round scanned **nothing** (18 already done) — resume works live.

### Decisions made

- **`run_label` as a first-class column**, not derived from `started_at`: makes the
  longitudinal series and resume explicit and unambiguous (worth a v2 migration).
- **"Done" = ok OR partial.** `partial` means the collector code raised (not a
  network failure — those keep status `ok`); a re-run would not fix it, and the
  monthly cadence re-scans anyway. `error`/`running`/absent → re-scanned.
- **DB writes serialized on the main thread**, workers do only network I/O — the
  simplest safe way to use stdlib sqlite3 with a thread pool.
- **Politeness = per-domain rate limiter × bounded concurrency**, queries aimed at
  public validating resolvers; one worker per domain keeps per-target load low.
  (No global cross-domain rate limiter — a shared DnsClient would leak query logs
  across domains; each domain gets its own client with a clean log.)

### Operational plan for the full run (decided this session)

- **Where.** The full 14,766 run does NOT go through Claude — `karne batch` is an
  independent OS process; Claude usage is spent only on conversation turns, not on
  the scan runtime, so Claude's session limit is irrelevant to the scan. Decision:
  run it in the **user's own terminal** (later, production monthly rounds → the VPS,
  Sprint 3). Resume makes interruption (sleep/network/reboot) safe: re-run the same
  `--run-label` and it continues.
- **How.** Single high-concurrency run, e.g.
  `uv run karne batch --run-label <YYYY-MM> --concurrency 10`. Raising concurrency
  is gentle — queries hit public resolvers and each domain still gets one paced
  worker, so per-target load is unchanged; it mainly cuts wall time (est. ~6–16 h
  at concurrency 4 → roughly a third at 10–12). Keep the machine awake.
- **`--dry-run` added** to `karne batch`: prints scope / already-done / pending +
  the per-status breakdown for the round and exits without scanning. For monitoring
  a long or chunked run without touching the network. (2 CLI tests; 119 offline now.)

### Known gaps / next steps

- **Full frame run NOT started.** The 18-domain bank subset validated the engine.
  The full 14,766 run is long and should be run deliberately (overnight); it resumes
  safely. Per-domain wall time is non-trivial (bank subset of 18 took several minutes
  at concurrency 4) because of DKIM's 16-selector sweep, MTA-STS HTTP, DANE per-MX
  TLSA, and timeout/servfail backoffs — budget accordingly for 14,766.
- **Scope is 14,767, not 14,766:** the leftover `internet.nl` (source=manual,
  Sprint 0) is still in `domains` and will be scanned too. Harmless; noted in Sprint 1.
- **Monthly cron (K-09) NOT set up** — deliberately deferred; must be discussed
  before wiring. Engine + manual run are solid first. Validation used label
  `2026-09` (current month); production monthly rounds begin per K-09.
- **IPv6/AAAA (Step 5, optional) SKIPPED this session.** Parity backlog item; the
  engine is complete without it. When added: hand-write expected output first, bump
  COLLECTOR_VERSION, update the PLAN parity table (still ⏳ Sprint 2 there).
- **First analysis notebook (Bulgu #1) NOT started** — better as its own session
  after the full run produces data. Turns raw data into "Türkiye's email-security
  report card".

### Next session starting point

Engine is done and validated. Options for next session: (1) kick off the **full
14,766 run** (resumable) and then (2) build the **first analysis notebook**
(Bulgu #1); (3) set up the **monthly cron** (needs a go/no-go discussion);
(4) optionally add **IPv6/AAAA** parity to dimension A.

---

## Sprint 1 · Session 1 — the Türkiye sample frame (COMPLETE)

**Sprint goal reached:** a reproducible, sector-labelled sample frame of **14,766
domains** written to the `domains` table, produced from the Tranco `.tr` subset +
a curated Turkish `.com` set. This is a LIST producer, not a collector — no domain
was scanned (that is Sprint 2).

### Method decisions (asked and confirmed this session)

- **Tranco access:** stdlib `urllib` CSV download (no new dependency). The
  **permanent list id** is recorded in the frame manifest, never hard-coded, so
  the same id reproduces the frame. (Confirmed over the `tranco` PyPI package.)
- **"Turkish site" definition (two-tier):** core universe = every `.tr` domain
  (exact, no judgement); expansion set = a curated, hand-asserted set of Turkish
  generic-TLD sites (`source=curated_tr_com`), never inferred. Generic-TLD domains
  not on the curated list are **excluded** (not labelled "not Turkish"). Written up
  and defended in `docs/frontier.md`. (Rejected an automatic IP/heuristic expansion
  as indefensible for now.)

### What was done (Steps 1–4)

- **Step 1 — `karne/frontier.py`** (pure, no-I/O core + thin download boundary):
  `.tr` detection (`is_dot_tr`, `tr_second_level`); `classify_sector()` with
  precedence **seed_list → tld_rule → keyword → unknown**, each carrying a
  provenance (`method` + `evidence`); `.tr` TLD rules (edu/gov/bel/pol/tsk →
  sector + is_public_body); curated per-sector seed lists; a tiny high-precision
  keyword set (`belediye`, `hastane`); Tranco parsing; `build_frame`,
  `sector_counts`, `method_counts`, `frame_manifest`; and passive list I/O
  (`tranco_download_url`, `fetch_tranco_csv`, `read_tranco_csv`).
  `docs/frontier.md` written (English per K-08).
- **Step 2 — 28 offline tests** (`tests/test_frontier.py`): fixture-based, no
  network; the five known targets and the honest "unknown" case asserted with
  hand-written expected output.
- **Step 3 — storage + CLI wiring.** `storage.add_domains()` (bulk upsert in one
  transaction: inserts new, refreshes frame metadata on existing, preserves
  `added_at`, de-dups the batch) and `storage.domain_sector_counts()`. New CLI
  command `karne frontier` (`--list-id` / `--tranco-file`, `--top`, `--no-curated`,
  `--no-store`, `--db`, `--manifest-dir`). 7 new tests (4 storage + 3 CLI).
- **Step 4 — built & verified on real data.** Ran `karne frontier --list-id Y8YQG`.
  14,766 domains (14,742 `.tr` from Tranco + 24 curated). All five targets land
  correctly: itu.edu.tr / istanbul.edu.tr → university (pub=1), garantibbva.com.tr
  → bank, turkiye.gov.tr → public_body (pub=1), mumifashion.com → ecommerce
  (curated). Manifest written to `data/frontier/frame_Y8YQG_<ts>.json`.

Tests: **97 offline pass**, 3 network deselected, ruff clean.

### Sector breakdown (frame Y8YQG, frontier 0.1.0)

unknown 13,665 · public_body 474 · university 287 · municipality 261 · hospital 30
· bank 18 · ecommerce 17 · media 14. `is_public_body` = 1,022. By method: none
13,665 · tld_rule 1,018 · seed_list 56 · keyword 27.

### Decisions made

- **No schema change for provenance.** The `domains` table stores only
  `sector` / `is_public_body` / `source`; per-row `method` is not a column. It is
  re-derivable by re-running the versioned pure `classify_sector`, and recorded at
  method+count granularity in the manifest. (Kept the sprint's "no refactor" rule.)
- **`add_domains` refreshes existing rows' frame metadata** (does not freeze them).
  Rule 5 protects raw `scan_results`, which this never touches; frame
  reproducibility lives in the per-run manifest. `added_at` is preserved.
- **is_public_body is a TLD/seed-criterion signal**, not a per-institution legal
  determination (edu.tr marks both state and foundation universities). Documented.

### Known gaps / limitations

- **Sector coverage is partial by design.** ~92.5% of the frame is `unknown`:
  seed lists cover a defensible subset and `.tr` TLD rules cover edu/gov/bel/pol/tsk
  broadly, but the large `com.tr` commercial mass is mostly unlabelled. Honest
  sampling limitation, recorded in the manifest — not a defect. Growing the seed
  lists (or moving them to a versioned `config/` file) is a future refinement.
- **Expansion set is small (24 curated `.com`).** Turkish institutions on generic
  TLDs are under-represented; the curated set can grow in later sessions.
- **Leftover non-frame domain kept:** `internet.nl` (source=manual, from Sprint 0)
  remains in `domains` — the frame builder never deletes rows. Correct behaviour;
  it is simply not part of the Türkiye frame.
- **Ethics board:** no code action; if the department requires approval, the
  application is due this month (PLAN.md section 4). Status unchanged this session.

### Next session starting point

Sprint 1 is done. Next is **Sprint 2 (November): first country-wide scan** — batch
scanning infrastructure (parallelism, rate limit, error handling, resumable scans),
applying dimension A to the whole frame, and the first analysis notebook. The
monthly cron starts this sprint. **Before batch scanning, decide the still-open
resolver questions** carried from Sprint 0: validating / multi-resolver choice and
the SERVFAIL re-query policy (turkiye.gov.tr and internet.nl showed why both
matter). Also add IPv6/AAAA presence (parity backlog) in Sprint 2.

---

## Sprint 0 · Session 2 — internet.nl parity: DANE + plan update

Triggered by comparing Karne against internet.nl (website + email tests) on
itu.edu.tr. internet.nl caught two things Karne was silent on: DANE and IPv6
(plus STARTTLS). On the overlapping indicators (SPF/DMARC/DKIM, DNSSEC) the two
tools agreed, which independently validates Karne's parsers.

### Done

- **Implemented DANE/TLSA** in `dns_email.py` (`parse_tlsa_record`,
  `collect_dane`), wired into `collect()` (MX resolved first to get the host
  list), the `dns_records` projection (rtype `TLSA`), and the CLI summary.
  Bumped `COLLECTOR_VERSION` to `0.2.0`. This was already promised in PLAN.md's
  dimension A table but got omitted from the Step 3 list.
- Tests: `parse_tlsa_record` (valid/out-of-range), `collect_dane`
  (present/absent hosts, null-MX skip), plus projection/summary assertions.
  62 offline tests pass, 3 network pass, ruff clean.
- Verified live: itu.edu.tr **0/2** MX hosts with TLSA (matches internet.nl's ❌
  for DANE); internet.nl **3/3** MX hosts with TLSA (parser confirmed correct).
- **Updated PLAN.md** with an "internet.nl ile kapsam denkliği (parity)"
  subsection: every internet.nl indicator mapped to a Karne dimension + sprint,
  and a STARTTLS scope-decision note added to section 4 (ethics).

### Parity backlog (added to PLAN.md, assigned to sprints)

- **IPv6 / AAAA** → Sprint 2 (passive: AAAA-record presence for web/MX/NS).
- **HTTPS / TLS / certificate / HSTS**, **security headers** → Sprint 3 (dim. B).
- **RPKI** → Sprint 5 (dim. D, infra).
- **STARTTLS** → **decided (2026-09-11): stay DNS-passive.** No live SMTP probe;
  K-07 preserved. Mail-transport security is covered DNS-side via MTA-STS +
  TLS-RPT + DANE. Revisitable in Sprint 3 (transport layer) if needed. PLAN.md
  section 4 records the decision.

### Live validation notes (scanning internet.nl)

Two documented limitations were confirmed live and are worth remembering:

- **DKIM selector guessing:** internet.nl uses DKIM but our common-selector list
  missed it (0/16). Karne correctly reports "none found (guessing)", not "no
  DKIM". Concrete thesis example of the method limitation.
- **DNSSEC AD flag depends on the resolver:** internet.nl is signed (DS present)
  yet `resolver_authenticated` was false, because the default resolver (a home
  router) does not validate DNSSEC. For accurate DNSSEC measurement the scan must
  use a validating resolver (e.g. 1.1.1.1 / 8.8.8.8). Fold this into the Sprint 2
  resolver decision alongside the SERVFAIL re-query policy.

---

## Sprint 0 · Session 1 — skeleton + DNS/email collector + CLI (COMPLETE)

**Sprint goal reached:** `karne scan <domain>` produces and stores the raw
DNS/email measurement (dimension A) of a domain.

### What was done (Steps 1–5)

- **Step 1 — skeleton.** Package layout from PLAN.md section 6, `CLAUDE.md`
  (six immutable rules + session protocol), `pyproject.toml` (uv + hatchling,
  ruff/pytest config), `.gitignore` (ignores `data/`), `.gitattributes` (LF),
  `README.md`, MIT `LICENSE`, `config/scoring.toml` skeleton. Renamed
  `docs/plan.md` → `docs/PLAN.md`. `git init` + first commit.
- **Step 2 — data layer.** `karne/models.py` (dataclasses) and
  `karne/storage.py` (stdlib sqlite3, WAL, full eight-table schema,
  `schema_version`, write/read helpers). `UNIQUE(scan_id, collector)` enforces
  rule 5. 17 storage tests.
- **Step 3 — collector.** `karne/collectors/dns_email.py`, `collect(domain) -> dict`.
  SPF (mechanisms, terminator, RFC 7208 lookup count over the include/redirect
  chain), DMARC, DKIM (selector guessing; key bits via a stdlib DER parser),
  MX (+ provider classification), MTA-STS (TXT + no-redirect GET), TLS-RPT,
  DNSSEC (DS + AD flag), CAA. `config/settings.toml` added. Full per-query log.
- **Step 4 — tests.** 50 offline tests for every brief case + the DnsClient
  exception→status mapping; 3 `network`-marked integration tests.
- **Step 5 — CLI + first measurement.** `karne/cli.py` (`scan`, `--json`,
  `--no-store`, `--db`, `--settings`). Payload→`dns_records` projection. Ran the
  five target domains; all stored. 8 CLI tests.

Commits: `3b78bf7`, `82acfcb`, `bc5fb3b`, `2f6e71c`, + Step 5. Tests: 58 offline
pass, 3 network pass, ruff clean.

### First-measurement findings (5 domains, 2026-09-10)

Factual observations only (scoring is Sprint 3):

- **mumifashion.com** — SPF `~all`; **DMARC `p=none`** (monitoring only, no
  enforcement), no `rua`; no DKIM on common selectors; no MTA-STS/DNSSEC/CAA.
- **itu.edu.tr** — SPF `-all`; **DMARC `p=reject` + `sp=reject`, `rua` present**
  (strong posture); DKIM `mail` RSA **1024-bit** (short key); MX self-hosted
  (`local`).
- **istanbul.edu.tr** — SPF `~all`; **DMARC `p=none`** (`pct=100`, `rua`
  present); DKIM `mailjet` RSA 1024; MX on Google.
- **garantibbva.com.tr** (bank) — SPF `-all`; **DMARC `p=reject`, `rua`
  present**; DKIM `selector1` RSA 1024; MX `other`.
- **turkiye.gov.tr** — SPF `-all` present, but DMARC/MX/MTA-STS/TLS-RPT/CAA all
  returned **SERVFAIL** at the system resolver. Recorded as `servfail`
  ("could not measure"), NOT as "no record" — exactly the rule-6 distinction.
  Note: TXT@apex succeeded while MX@apex servfailed, so this looks like a
  resolver/authoritative quirk; may be intermittent.

### Decisions made

- Full eight-table schema now; `cookies`/`requests` are schema-only until Sprint 4.
- No new dependency for DKIM key length — a small stdlib DER parser extracts the
  RSA modulus bit length (accurate); ed25519 reported as raw key size.
- Query status set extended with `noanswer` (NODATA) so "name exists, no record
  of this type" stays distinct from NXDOMAIN and from errors (rule 6).
- SPF lookup count follows include/redirect recursively; a/mx/ptr/exists counted
  as one each without expanding sub-lookups (`method` recorded; raw chain kept).
- DNSSEC "validation" is the resolver's AD flag, explicitly noted as such.
- Summary output is ASCII-only (Windows console safety) and strictly factual.

### Known gaps / limitations

- DKIM relies on selector guessing (inherent; flagged `method=selector_guessing`).
- SERVFAIL handling for batch scanning (Sprint 2) likely needs re-querying and/or
  multiple resolvers — a single resolver can mask records (see turkiye.gov.tr).
- `config/settings.toml` `user_agent` URL is a placeholder — update when the
  project page exists.
- No scoring yet (by design — Sprint 3). `scores`/`findings` tables stay empty.

### Next session starting point

Sprint 0 is done. Next is **Sprint 1 (October): the Türkiye sample frame** —
`karne/frontier.py`, Tranco + `.tr` extraction, sector labelling. Batch scanning
infrastructure is Sprint 2. Before batch scans, decide the multi-resolver /
re-query policy for SERVFAIL.
