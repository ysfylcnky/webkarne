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
- **Analysis notebook (Bulgu #1) NOT built** — deliberately a separate job (PLAN §8.4).
  The engine + full scored data are ready to feed it.

### Next session starting point

Scoring engine (dimension A) is done, versioned (1.1.0), and applied to the whole frame.
Options: (1) build the **Bulgu #1 analysis notebook** turning scored data into "Türkiye's
email-security report card" (skeleton in `notebooks/`); (2) start **dimension B (TLS/HTTP)
collector** — the next Sprint 3 module; (3) begin **FastAPI + bilingual UI** and the
translation files that back the finding `fix_hint_key`s. Sprint 2's batch work and this
scoring work are still **uncommitted** in the working tree — commit before starting.
