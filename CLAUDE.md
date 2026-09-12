# CLAUDE.md — working rules for the Karne project

This file defines **how** we build Karne. `docs/PLAN.md` defines **what** we build
and **why** (it is the single source of truth; it is written in Turkish and stays
Turkish). `docs/PROGRESS.md` records **how far** we have come.

## Session protocol

- **At the start of every session, read three files:** `CLAUDE.md`, `docs/PLAN.md`,
  and `docs/PROGRESS.md`. They are the project's persistent memory.
- **At the end of every session:** prepend the new session record to the top of
  `docs/PROGRESS-ARCHIVE.md` (newest first), and update the **Mevcut durum**
  (current-state) section of `docs/PROGRESS.md`. `docs/PROGRESS.md` never exceeds
  one page; if it grows past that, the older content is moved into the archive.
- **All UI work is governed by `docs/DESIGN-SYSTEM.md`.** No raw colour, spacing,
  font size, radius or duration value is written anywhere except
  `karne/web/static/tokens.css`. A missing value is defined there first (and
  recorded in `docs/DESIGN-SYSTEM.md`), never inlined.
- **One session, one module.** Collectors are deliberately small and independent.
  "Write the SPF parser and test it on these ten domains" is a good task;
  "build the privacy module" is not.
- **Expected output before code.** For each collector, hand-write the expected
  result of a known domain and put it in a test. In measurement code the most
  dangerous bug is the silent one: the code runs, produces a number, and the
  number is wrong.
- **If something must deviate from `docs/PLAN.md`, update the plan first, then the
  code.** Do not silently diverge.

## Immutable rules

These are non-negotiable. They protect the scientific validity of the dataset and
the ethical boundary of the project.

1. **Collectors never interpret.** A collector records exactly what it observed as
   raw JSON. It produces no score, no letter grade, no "good/bad" judgement.
   Scoring is a completely separate layer that can be re-run later against stored
   raw data. (PLAN.md K-02.)
2. **Scoring rules are not embedded in code.** They live in `config/scoring.toml`
   with a version number. Every score record states which ruleset version produced
   it. (PLAN.md K-03.) *(Sprint 0: skeleton file only.)*
3. **Each collector is an independent, single-responsibility module.** If one
   crashes, the scan continues with a partial result and the error is written to
   the `scans.error` field. (PLAN.md K-05.)
4. **Passive measurement only.** DNS queries and ordinary HTTP GET, nothing more.
   No vulnerability scanning, directory/file brute-forcing, port scanning, or DNS
   zone transfer (AXFR). A timeout and a rate limit are mandatory on every request.
   (PLAN.md K-07, section 4.)
5. **Raw data is never deleted or overwritten.** Every scan is a new record.
   (PLAN.md K-02, K-10.)
6. **No silent failures.** If a query fails, the result is recorded as
   "could not measure", never as "no record". `NXDOMAIN` and a query error
   (timeout / servfail / other) are recorded as **distinct** states. This
   distinction is critical for the accuracy of the measurement.

## Language

Code, identifiers, comments, commit messages, `README.md`, and developer-facing
documentation are in **English**. `docs/PLAN.md` stays **Turkish**. User-facing
UI/report text will be bilingual (tr/en) via translation files in later sprints —
not a concern in Sprint 0. (PLAN.md K-08.)

## Repository layout

```
karne/
  CLAUDE.md                 # this file — how we work
  pyproject.toml            # project + deps (managed with uv), ruff & pytest config
  docs/
    PLAN.md                 # the plan (Turkish, source of truth)
    PROGRESS.md             # updated at the end of every session
  config/
    settings.toml           # scan parameters: timeouts, rate limits, selector lists
    scoring.toml            # weights, thresholds, grade cut-offs (versioned)
  karne/
    __init__.py
    models.py               # dataclasses for the data model
    storage.py              # SQLite layer (stdlib sqlite3, WAL, plain SQL — no ORM)
    frontier.py             # domain list + sector labels (Sprint 1)
    cli.py                  # `karne scan / batch / rescore / export`
    collectors/             # one file per dimension, each `collect(domain) -> dict`
      dns_email.py          # dimension A (Sprint 0)
      tls_http.py           # dimension B (Sprint 3)
      web_privacy.py        # dimension C (Sprint 4, Playwright)
      fingerprint.py        # dimension D (Sprint 5)
    analyze/                # raw -> scores/findings (separate layer)
    api/                    # FastAPI (Sprint 3)
    web/                    # UI + i18n (Sprint 3)
  data/karne.db             # gitignored; created at runtime
  notebooks/                # analysis notebooks that produce thesis findings
  paper/                    # thesis text and figures
  tests/
```

## Stack & tooling

- **Python** 3.12+ (developed on 3.14).
- **Package management:** `uv`. Add a dependency with `uv add <pkg>`; run commands
  with `uv run <cmd>`.
- **CLI:** `typer`. **DNS:** `dnspython`. **Storage:** stdlib `sqlite3` (WAL mode),
  plain SQL, **no ORM**. **Config:** stdlib `tomllib` (read-only). **HTTP GET:**
  stdlib `urllib` (single short request for MTA-STS; no new dependency).
- **Tests:** `pytest`. **Lint/format:** `ruff`.
- **Ask before adding any new dependency.** Keep the dependency count low.

Common commands:

```bash
uv sync                       # create/refresh the environment
uv run karne scan example.com # run a scan
uv run pytest -m "not network"# unit tests (offline, default)
uv run pytest -m network      # integration tests (need live DNS)
uv run ruff check .           # lint
uv run ruff format .          # format
```

## Code style

- Small, single-purpose functions; pure parsers separated from I/O so they can be
  unit-tested against fixtures with no network.
- Type hints everywhere. `dataclasses` for records. Plain SQL strings for storage.
- No broad `except:`; catch specific exceptions and record the failure state
  (rule 6). Never swallow an error into a "no record" result.
- Every network call sets an explicit timeout and honours the configured rate limit
  and concurrency (rule 4).

## Do NOT (in general)

- Do not let a collector emit scores, grades, or judgements (rule 1).
- Do not hard-code scoring rules; they belong in `config/scoring.toml` (rule 2).
- Do not delete or overwrite raw scan data (rule 5).
- Do not perform any active/intrusive probe (rule 4, PLAN.md section 4):
  no exploits, login attempts, form submission, directory/port scanning, or AXFR.
- Do not conflate `NXDOMAIN` with a query error (rule 6).
- Do not add a dependency without asking.

## Active sprint — Sprint 1 (October): the Türkiye sample frame

**Sprint 0 is COMPLETE** (2026-09-11): repo skeleton, SQLite schema, the
`karne scan <domain>` command, and dimension A (DNS/email) including DANE/TLSA.
Verified on the five target domains; 62 offline + 3 network tests pass. See
docs/PROGRESS.md for the full record and carried-over decisions.

**In scope (Sprint 1):** `karne/frontier.py` — build the Türkiye universe from the
Tranco list and `.tr` extensions; sector labelling (bank, university, public body,
municipality, hospital, e-commerce, media); and a written, defensible definition of
"a Turkish site" (a method decision for the thesis). Ethics-board application this
month if the department requires it. Output: a ~10,000-domain, sector-labelled
sample frame. (PLAN.md section 7.)

**Carried-over for batch scanning (Sprint 2):** the validating-resolver /
multi-resolver choice and the SERVFAIL re-query policy (see docs/PROGRESS.md).

**Still out of scope (do not build yet):** web UI, FastAPI, Playwright/browser
measurement (dimension C), TLS/HTTP (dimension B), the scoring engine, batch
scanning, Docker, CI. These are later sprints (see PLAN.md section 7).
