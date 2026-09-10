# Karne

Karne measures the **digital hygiene** of an organisation's domain and turns the
result into an explained report card ("karne" means *report card* in Turkish).
It is both a public, working measurement tool and the empirical backbone of a
master's thesis on the state of digital hygiene among institutions in Türkiye.

Given a domain, Karne measures four dimensions:

- **A — Email & domain identity** — SPF, DMARC, DKIM, MX, MTA-STS/TLS-RPT, DANE,
  DNSSEC, CAA. *(Pure DNS; implemented first.)*
- **B — Transport & server security** — HTTPS enforcement, TLS config, certificate,
  HSTS, security headers, cookies.
- **C — Privacy & tracking** — cookies, storage, third-party requests, trackers and
  fingerprinting, measured in three consent states (untouched / rejected / accepted).
- **D — Technology & visible surface** — platform, plugins, JS libraries, infra,
  derived from the other collectors' data.

## Design principles

- **Raw observation and scoring are strictly separate.** Collectors record exactly
  what they observed as raw JSON and never judge it. Scores and findings are derived
  later, so past scans can be re-scored as the rules evolve.
- **Scoring rules live in data, not code** (`config/scoring.toml`, versioned).
- **Passive and public only.** Karne does nothing beyond what an ordinary visitor's
  browser and public DNS expose: no vulnerability scanning, directory/port probing,
  form submission, or DNS zone transfer. Every request is rate-limited and has a
  timeout.
- **No silent failures.** A failed query is recorded as "could not measure", kept
  distinct from "no record" (e.g. `NXDOMAIN` ≠ `timeout`).

See `docs/PLAN.md` for the full plan (in Turkish) and `CLAUDE.md` for the working
rules.

## Status

**Sprint 0 (Sep 2026): skeleton + first measurement.** Building the `karne scan`
command for dimension A only. The other dimensions, the scoring engine, the web UI,
and batch scanning come in later sprints.

## Getting started

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # create the environment
uv run karne scan example.com    # scan a domain (available from Step 5)
uv run pytest                    # run the offline unit tests
```

## License

MIT (see `LICENSE`). The measurement **dataset** is released separately, at thesis
submission (PLAN.md K-10).
