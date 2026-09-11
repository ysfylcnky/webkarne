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
