# PROGRESS

Running log of the project. Updated at the **end of every session** (see CLAUDE.md).
Each entry records: what was done, decisions made, known gaps, and the starting
point for the next session. Newest session last.

The three persistent-memory files are `docs/PLAN.md` (what/why), `CLAUDE.md` (how),
and this file (how far).

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
