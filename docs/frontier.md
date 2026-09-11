# The Türkiye sample frame — definition and method

*Sprint 1 method document. Developer-facing, so written in English per CLAUDE.md
K-08 (only `docs/PLAN.md` stays Turkish). This is the defensible write-up of two
method decisions the thesis will reuse: **what counts as a Turkish site**, and
**how a sector label is assigned**. The code that implements it is
`karne/frontier.py`; scanning the domains is out of scope here (Sprint 2).*

## What the frame is (and is not)

The frame is the **population of domains Karne intends to measure**, each tagged
with a `sector` and an `is_public_body` flag. It is a *list producer*, not a
collector: it performs no measurement of the domains, emits no score, and makes no
quality judgement. A sector label answers "what kind of institution is this?" — it
says nothing about whether the institution's hygiene is good or bad. (This is the
Sprint-1 reading of the immutable rule *"collectors never interpret."*)

## Decision 1 — the definition of "a Turkish site"

There is no authoritative registry of "Turkish websites", so the boundary is a
method decision that must be stated and defended rather than assumed. We use a
**two-tier definition**:

### Core universe — the `.tr` ccTLD (exact, no judgement)

Every domain under the **`.tr`** country-code TLD is in the frame. `.tr`
registration is administered for Türkiye, so membership is a fact, not an
inference: `domain.endswith(".tr")`. This tier is fully reproducible and needs no
curation.

### Expansion set — curated Turkish generic-TLD sites (explicit, flagged)

Many prominent Turkish institutions operate on generic TLDs (`.com`, `.net`,
`.org`) — e.g. `trendyol.com`, `akbank.com`, `mumifashion.com`. Restricting to
`.tr` alone would silently drop them. We therefore add a **curated, hand-asserted**
set of well-known Turkish generic-TLD sites, each written to the `domains` table
with `source = "curated_tr_com"` so it is always separable from the `.tr` core.

**We do not *infer* Turkishness of a generic-TLD domain.** A `.com` domain enters
the frame only by explicit curation. Generic-TLD domains that are *not* on the
curated list are simply **excluded** from the frame — this is deliberately kept
distinct from labelling something "not Turkish". We considered an automatic
expansion (IP geolocation / language / TLD heuristics) and rejected it for Sprint 1:
it is the hardest tier to defend, is prone to false positives, and would require
contacting domains (out of scope). It can be revisited later as its own, clearly
flagged tier.

**Known limitation.** The core universe is exhaustive for `.tr`; the expansion set
is intentionally partial. The frame under-represents Turkish institutions that use
generic TLDs and are not yet curated. This is an honest boundary of the sampling
method, recorded here and in `PROGRESS.md`, not a defect to hide.

## Decision 2 — sector labelling

Seven sectors plus an honest `unknown`: **bank, university, public_body,
municipality, hospital, ecommerce, media, unknown**. A domain whose sector cannot
be determined is left `unknown` — never forced into a sector (no silent errors).

Every label carries a **provenance** (`method` + `evidence`), assigned by the first
matching rule in this precedence:

1. **`seed_list`** — exact match in a curated per-sector seed list
   (`karne.frontier.SECTOR_SEEDS`). Highest confidence; covers well-known banks,
   e-commerce, media and hospital brands, including those on `.com.tr`/`.com`.
2. **`tld_rule`** — the `.tr` second-level label, when it has a reliable
   institutional meaning:

   | `.tr` second level | sector        | `is_public_body` |
   |--------------------|---------------|------------------|
   | `edu.tr`           | university    | yes              |
   | `gov.tr`           | public_body   | yes              |
   | `bel.tr`           | municipality  | yes              |
   | `pol.tr`           | public_body   | yes              |
   | `tsk.tr`           | public_body   | yes              |

   Commercial second levels (`com.tr`, `net.tr`, `org.tr`, `gen.tr`, `web.tr`, …)
   carry no sector signal and fall through.
3. **`keyword`** — a deliberately tiny, high-precision keyword set applied to the
   domain text (currently `belediye` → municipality, `hastane` → hospital). Noisy
   tokens (e.g. "bank", "haber", "universite" as substrings) are **excluded** and
   left to the seed lists, to avoid mislabelling. Flagged `method = keyword`.
4. **`none`** — no signal matched → `unknown`.

### The `is_public_body` flag

`is_public_body` is a **positive detection**: `True` means a public-body criterion
matched (`gov.tr` / `bel.tr` / `edu.tr` / `pol.tr` / `tsk.tr`, or a public/municipal
seed); `False` means none did. Note that `edu.tr` marks both state and foundation
universities as public bodies — this is a TLD-criterion signal (the brief's
definition), **not** a per-institution legal determination, and is documented as
such rather than resolved here.

### Coverage is partial by design

Seed lists cover a defensible, well-known subset; the `.tr` TLD rules cover
universities, government, municipalities, police and armed forces broadly. The
large commercial remainder (`com.tr` and curated `.com`) that isn't in a seed list
stays `unknown`. This partial coverage is expected and is reported in the manifest
(`method_counts`, `sector_counts`), so the labelled subset and its provenance are
always auditable.

## Reproducibility

A frame is a deterministic function of two versioned inputs:

- **The Tranco list identity.** Tranco lists change daily, so we use a **permanent
  list id** (`tranco-list.eu/list/<ID>`) and download it via `/download/<ID>/full`.
  The id and download URL are recorded in the **frame manifest** (output metadata),
  never hard-coded. The same id yields the same input list.
- **The frontier ruleset.** `FRONTIER_VERSION` versions the classification rules and
  seed lists in `karne/frontier.py`. The same version yields the same labels.

The manifest (`frame_manifest`) records `frontier_version`, `tranco_list_id`,
`tranco_source_url`, `cctld_source`, totals, and per-source/sector/method counts.
Because classification is a pure function of the (versioned) rules, the per-domain
method is always re-derivable by re-running `classify_sector`, so provenance is
preserved even though the `domains` table stores only `sector` / `is_public_body` /
`source` (no schema change this sprint — see PROGRESS.md).

Raw list files are downloaded to `data/` (gitignored) and never overwritten; each
frame version is stored with its source manifest.
