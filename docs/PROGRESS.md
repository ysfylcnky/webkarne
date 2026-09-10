# PROGRESS

Running log of the project. Updated at the **end of every session** (see CLAUDE.md).
Each entry records: what was done, decisions made, known gaps, and the starting
point for the next session. Newest session last.

The three persistent-memory files are `docs/PLAN.md` (what/why), `CLAUDE.md` (how),
and this file (how far).

---

## Sprint 0 · Session 1 — skeleton + DNS/email collector

**Goal of the sprint:** one command, `karne scan <domain>`, that produces and stores
the raw DNS/email measurement (dimension A) of a domain.

### Step 1 — skeleton (in progress)

Done:

- Renamed `docs/plan.md` → `docs/PLAN.md` to match the documented layout and be
  safe on case-sensitive filesystems (the Linux VPS). Content unchanged.
- Created the package layout from PLAN.md section 6: `karne/` with
  `collectors/`, `analyze/`, `api/`, `web/`, plus `config/`, `data/`, `tests/`,
  `notebooks/`, `paper/`.
- Wrote `CLAUDE.md`: the six immutable rules, session protocol, layout, stack,
  code style, a "do not" list, and the active Sprint 0 scope.
- Created `docs/PROGRESS.md` (this file).
- Wrote `pyproject.toml` (uv-managed, hatchling build), ruff + pytest config,
  `.gitignore` (ignores `data/`), and an English `README.md`.
- Created `config/scoring.toml` as a **versioned skeleton only** (no scoring logic
  — that starts in Sprint 3).
- `git init` + first commit.

Decisions:

- **Dependencies kept minimal.** Runtime: `typer`, `dnspython`. Dev: `pytest`,
  `ruff`. Config is read with stdlib `tomllib`; the single MTA-STS HTTP GET will
  use stdlib `urllib` — no HTTP-client dependency added in Sprint 0.
- `requires-python = ">=3.12"`; developed on the locally installed Python 3.14.
- `config/settings.toml` is **not** created in Step 1; it is introduced in Step 3
  when the collector actually reads selector lists / network parameters from it.

Known gaps / next starting point:

- Step 2: data layer (`karne/models.py`, `karne/storage.py`) + storage tests.
- Then Step 3 (DNS/email collector), Step 4 (offline parser tests), Step 5 (CLI +
  first real measurements on the five target domains).
