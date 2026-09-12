"""Türkiye sample frame — Sprint 1.

This module builds the *sample frame* for Karne: the reproducible list of domains
that later sprints will measure, each tagged with a sector and an ``is_public_body``
flag. It is **not** a collector. There is no ``collect()`` here, no raw measurement,
no network probing of the domains themselves — the only network access is
downloading a public domain-ranking list (Tranco), which is passive list I/O.

Design constraints for this sprint (CLAUDE.md, adapted):

- **Reproducible.** A frame is a deterministic function of (a) a specific Tranco
  list identity, recorded by its permanent list id + date, and (b) the versioned
  classification rules in this module (``FRONTIER_VERSION``). The same inputs must
  produce the same frame. The list id goes into the output manifest, not the code
  (download it to ``data/`` and pass the id in).
- **No silent errors.** A domain whose sector cannot be determined is labelled
  ``"unknown"`` (never forced into a sector). "Not a Turkish site" (excluded from
  the frame) and "unsure of the sector" (``unknown``) are kept distinct.
- **A sector label is a classification, not a quality judgement.** The immutable
  rule "collectors never interpret" applies here as: a sector tag describes *what
  kind of institution* a domain is, and asserts nothing about how good or secure
  it is.
- **Provenance is recorded.** Every classification carries a ``method``
  (``tld_rule`` / ``seed_list`` / ``keyword`` / ``none``) and an ``evidence`` string,
  so how each label was assigned is inspectable and re-derivable.

The "Turkish site" definition and the sector method are written up and defended in
``docs/frontier.md``. Pure functions (parsing, ``.tr`` detection, classification,
frame assembly) take no I/O and are unit-tested against fixtures with no network;
the Tranco download is confined to the thin I/O helpers at the bottom.
"""

from __future__ import annotations

import csv
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Bumped whenever the classification rules or seed lists change. Recorded in the
# frame manifest so a frame can be tied to the exact ruleset that produced it.
FRONTIER_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

# Sector labels. "unknown" is a first-class, honest value — not a failure.
SECTOR_BANK = "bank"
SECTOR_UNIVERSITY = "university"
SECTOR_PUBLIC_BODY = "public_body"
SECTOR_MUNICIPALITY = "municipality"
SECTOR_HOSPITAL = "hospital"
SECTOR_ECOMMERCE = "ecommerce"
SECTOR_MEDIA = "media"
SECTOR_UNKNOWN = "unknown"

SECTORS = (
    SECTOR_BANK,
    SECTOR_UNIVERSITY,
    SECTOR_PUBLIC_BODY,
    SECTOR_MUNICIPALITY,
    SECTOR_HOSPITAL,
    SECTOR_ECOMMERCE,
    SECTOR_MEDIA,
    SECTOR_UNKNOWN,
)

# How a sector label was assigned (provenance).
METHOD_TLD_RULE = "tld_rule"  # from the .tr second-level label (e.g. edu.tr)
METHOD_SEED_LIST = "seed_list"  # exact match in a curated seed list
METHOD_KEYWORD = "keyword"  # high-precision keyword in the domain label
METHOD_NONE = "none"  # no signal -> SECTOR_UNKNOWN

# Domain-origin markers written to domains.source.
SOURCE_TRANCO = "tranco"  # appeared in the Tranco .tr subset
SOURCE_CURATED_TR_COM = "curated_tr_com"  # curated Turkish .com/.net/.org site

# ---------------------------------------------------------------------------
# The "Turkish site" definition (see docs/frontier.md)
# ---------------------------------------------------------------------------
#
# Core universe  = every domain under the ``.tr`` ccTLD. This is exact and needs no
#                   judgement: ``.tr`` registration is administered for Türkiye.
# Expansion set  = a curated, explicitly flagged set of well-known Turkish sites on
#                   generic TLDs (.com/.net/.org). Membership is asserted by hand
#                   (source = "curated_tr_com"), never inferred — so it stays
#                   defensible and reproducible. Generic-TLD domains NOT on this
#                   list are left out of the frame (we do not guess Turkishness).


def is_dot_tr(domain: str) -> bool:
    """True if ``domain`` is under the ``.tr`` ccTLD (last label is ``tr``)."""
    return domain.endswith(".tr")


def tr_second_level(domain: str) -> str | None:
    """Return the second-level label under ``.tr`` (``edu`` for ``itu.edu.tr``).

    Returns ``None`` for non-``.tr`` domains and for a bare second-level ``.tr``
    registration (``example.tr``) that has no category label.
    """
    if not is_dot_tr(domain):
        return None
    labels = domain.split(".")
    if len(labels) < 3:
        return None
    return labels[-2]


# ---------------------------------------------------------------------------
# .tr second-level rules
# ---------------------------------------------------------------------------
#
# Maps a .tr second-level label to (sector, is_public_body). Only labels with a
# reliable institutional meaning are mapped; commercial labels (com/net/org/gen/
# web/biz/info/name/tv...) carry no sector signal and fall through to seeds/keywords.
#
# is_public_body follows the criterion stated in the sprint brief: gov.tr, bel.tr,
# edu.tr, pol.tr and tsk.tr are treated as public bodies. (edu.tr covers both state
# and foundation universities; the flag is a TLD-criterion signal, documented as
# such in docs/frontier.md — it is not a per-institution legal determination.)
TR_TLD_RULES: dict[str, tuple[str, bool]] = {
    "edu": (SECTOR_UNIVERSITY, True),
    "gov": (SECTOR_PUBLIC_BODY, True),
    "bel": (SECTOR_MUNICIPALITY, True),
    "pol": (SECTOR_PUBLIC_BODY, True),  # police
    "tsk": (SECTOR_PUBLIC_BODY, True),  # armed forces
}


# ---------------------------------------------------------------------------
# Curated seed lists (versioned with FRONTIER_VERSION)
# ---------------------------------------------------------------------------
#
# Exact registrable-domain -> sector. Deliberately partial: seeds cover a
# defensible, well-known subset; everything else stays "unknown" (an honest
# limitation, recorded in the manifest, not a gap to paper over). Entries on
# generic TLDs double as the "Turkish .com" expansion set (CURATED_TR_COM below).

_BANK_SEEDS = {
    "garantibbva.com.tr",
    "isbank.com.tr",
    "yapikredi.com.tr",
    "ziraatbank.com.tr",
    "vakifbank.com.tr",
    "halkbank.com.tr",
    "teb.com.tr",
    "ing.com.tr",
    "sekerbank.com.tr",
    "odeabank.com.tr",
    "fibabanka.com.tr",
    "kuveytturk.com.tr",
    "albaraka.com.tr",
    "turkiyefinans.com.tr",
    "qnb.com.tr",
    "akbank.com",
    "denizbank.com",
    "enpara.com",
}

_ECOMMERCE_SEEDS = {
    "trendyol.com",
    "hepsiburada.com",
    "n11.com",
    "ciceksepeti.com",
    "morhipo.com",
    "teknosa.com",
    "vatanbilgisayar.com",
    "getir.com",
    "mumifashion.com",
    "lcw.com",
    "koton.com",
    "defacto.com.tr",
    "boyner.com.tr",
    "a101.com.tr",
    "migros.com.tr",
    "mediamarkt.com.tr",
    "gratis.com",
}

_MEDIA_SEEDS = {
    "hurriyet.com.tr",
    "milliyet.com.tr",
    "sozcu.com.tr",
    "sabah.com.tr",
    "ntv.com.tr",
    "cnnturk.com",
    "haberturk.com",
    "cumhuriyet.com.tr",
    "t24.com.tr",
    "birgun.net",
    "trthaber.com",
    "aa.com.tr",
    "donanimhaber.com",
    "webtekno.com",
}

_HOSPITAL_SEEDS = {
    "acibadem.com.tr",
    "memorial.com.tr",
    "medicalpark.com.tr",
    "florence.com.tr",
    "dunyagoz.com",
    "livhospital.com",
    "anadolusaglik.org",
}

# Sector seeds keyed by domain (flattened). University/public-body/municipality are
# handled primarily by the .tr TLD rules, so they need few or no seeds here.
SECTOR_SEEDS: dict[str, str] = {
    **dict.fromkeys(_BANK_SEEDS, SECTOR_BANK),
    **dict.fromkeys(_ECOMMERCE_SEEDS, SECTOR_ECOMMERCE),
    **dict.fromkeys(_MEDIA_SEEDS, SECTOR_MEDIA),
    **dict.fromkeys(_HOSPITAL_SEEDS, SECTOR_HOSPITAL),
}

# The Turkish-site expansion set: seed domains that are NOT under .tr. These are
# added to the frame explicitly (source = curated_tr_com) even if absent from the
# Tranco .tr subset, because the .tr filter alone would miss them.
CURATED_TR_COM = frozenset(d for d in SECTOR_SEEDS if not is_dot_tr(d))


# ---------------------------------------------------------------------------
# High-precision keyword rules
# ---------------------------------------------------------------------------
#
# A weak, last-resort signal, kept intentionally tiny and high-precision. Only
# tokens that are near-unambiguous in Turkish institutional naming are used; noisy
# tokens (bank/haber/universite as substrings) are deliberately excluded and left
# to seeds. Applied to the registrable-domain text; always flagged method=keyword.
_KEYWORD_RULES: tuple[tuple[str, str, bool], ...] = (
    ("belediye", SECTOR_MUNICIPALITY, True),
    ("hastane", SECTOR_HOSPITAL, False),
)


@dataclass(frozen=True)
class Classification:
    """The sector decision for one domain, with its provenance.

    ``sector`` is one of :data:`SECTORS`. ``is_public_body`` is a positive
    detection: ``True`` means a public-body criterion matched (see docs), ``False``
    means none did. ``method`` and ``evidence`` record how the label was assigned.
    """

    sector: str
    is_public_body: bool
    method: str
    evidence: str | None


def classify_sector(domain: str) -> Classification:
    """Classify a single domain's sector. Pure; no network.

    Precedence: curated seed list (most specific) -> .tr TLD rule -> keyword ->
    unknown. A domain with no signal is ``SECTOR_UNKNOWN`` / ``method_none`` — never
    forced into a sector.
    """
    domain = domain.strip().rstrip(".").lower()

    # 1. Curated seed list — exact match, highest confidence.
    seed_sector = SECTOR_SEEDS.get(domain)
    if seed_sector is not None:
        return Classification(
            sector=seed_sector,
            is_public_body=seed_sector in (SECTOR_PUBLIC_BODY, SECTOR_MUNICIPALITY),
            method=METHOD_SEED_LIST,
            evidence=f"seed:{seed_sector}",
        )

    # 2. .tr second-level rule.
    sld = tr_second_level(domain)
    if sld is not None and sld in TR_TLD_RULES:
        sector, is_public = TR_TLD_RULES[sld]
        return Classification(
            sector=sector,
            is_public_body=is_public,
            method=METHOD_TLD_RULE,
            evidence=f"{sld}.tr",
        )

    # 3. High-precision keyword (last resort).
    for token, sector, is_public in _KEYWORD_RULES:
        if token in domain:
            return Classification(
                sector=sector,
                is_public_body=is_public,
                method=METHOD_KEYWORD,
                evidence=f"keyword:{token}",
            )

    # 4. No signal — honest "unknown".
    return Classification(
        sector=SECTOR_UNKNOWN,
        is_public_body=False,
        method=METHOD_NONE,
        evidence=None,
    )


# ---------------------------------------------------------------------------
# Tranco line parsing (pure)
# ---------------------------------------------------------------------------


def parse_tranco_line(line: str) -> tuple[int, str] | None:
    """Parse one ``rank,domain`` line of a Tranco full CSV.

    Returns ``(rank, normalized_domain)`` or ``None`` for a blank/malformed line
    (missing field, non-integer rank, empty domain). The domain is lower-cased and
    stripped of surrounding whitespace and a trailing dot.
    """
    line = line.strip()
    if not line:
        return None
    parts = line.split(",")
    if len(parts) < 2:
        return None
    rank_str, domain = parts[0].strip(), parts[1].strip().rstrip(".").lower()
    if not domain:
        return None
    try:
        rank = int(rank_str)
    except ValueError:
        return None
    return rank, domain


def parse_tranco_rows(lines: Iterable[str]) -> Iterator[tuple[int, str]]:
    """Yield ``(rank, domain)`` for every parseable line; skip malformed ones."""
    for line in lines:
        parsed = parse_tranco_line(line)
        if parsed is not None:
            yield parsed


# ---------------------------------------------------------------------------
# Frame assembly (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameEntry:
    """One domain in the sample frame, ready to write to the ``domains`` table."""

    domain: str
    source: str  # SOURCE_TRANCO | SOURCE_CURATED_TR_COM
    sector: str
    is_public_body: bool
    method: str  # sector-label provenance
    evidence: str | None
    rank: int | None = None  # Tranco rank if known (None for curated-only entries)


def build_frame(
    tranco_rows: Iterable[tuple[int, str]],
    *,
    include_curated: bool = True,
    curated_domains: Iterable[str] = CURATED_TR_COM,
) -> list[FrameEntry]:
    """Assemble the Türkiye frame from parsed Tranco rows. Pure; no network.

    Two passes:

    1. Keep every ``.tr`` domain from the Tranco list (source = tranco), classified.
    2. Add each curated Turkish generic-TLD domain (source = curated_tr_com),
       reusing its Tranco rank if it happened to appear in the list.

    Entries are de-duplicated by domain and returned ranked (ranked entries first,
    then curated-only, then alphabetical) for a stable, reproducible order.
    """
    rank_map: dict[str, int] = {}
    entries: dict[str, FrameEntry] = {}

    for rank, domain in tranco_rows:
        # Keep the best (smallest) rank if a domain appears more than once.
        if domain not in rank_map or rank < rank_map[domain]:
            rank_map[domain] = rank
        if is_dot_tr(domain) and domain not in entries:
            c = classify_sector(domain)
            entries[domain] = FrameEntry(
                domain=domain,
                source=SOURCE_TRANCO,
                sector=c.sector,
                is_public_body=c.is_public_body,
                method=c.method,
                evidence=c.evidence,
                rank=rank,
            )

    # Reconcile each .tr entry to the smallest rank seen for it (a domain may
    # recur in the list; the best rank wins). Tranco is normally sorted, so this
    # is a no-op in practice, but we honour the smallest-rank rule regardless.
    entries = {d: _with_rank(e, rank_map.get(d)) for d, e in entries.items()}

    if include_curated:
        for domain in curated_domains:
            domain = domain.strip().rstrip(".").lower()
            if domain in entries:
                continue
            c = classify_sector(domain)
            entries[domain] = FrameEntry(
                domain=domain,
                source=SOURCE_CURATED_TR_COM,
                sector=c.sector,
                is_public_body=c.is_public_body,
                method=c.method,
                evidence=c.evidence,
                rank=rank_map.get(domain),
            )

    return sorted(entries.values(), key=lambda e: (e.rank is None, e.rank or 0, e.domain))


def _with_rank(entry: FrameEntry, rank: int | None) -> FrameEntry:
    """Return ``entry`` with its rank set to the smallest of the two known ranks."""
    if rank is None:
        return entry
    if entry.rank is not None:
        rank = min(entry.rank, rank)
    if rank == entry.rank:
        return entry
    return FrameEntry(
        domain=entry.domain,
        source=entry.source,
        sector=entry.sector,
        is_public_body=entry.is_public_body,
        method=entry.method,
        evidence=entry.evidence,
        rank=rank,
    )


def sector_counts(entries: Iterable[FrameEntry]) -> dict[str, int]:
    """Count entries per sector (all sectors present, zero-filled)."""
    counts = dict.fromkeys(SECTORS, 0)
    for e in entries:
        counts[e.sector] = counts.get(e.sector, 0) + 1
    return counts


def method_counts(entries: Iterable[FrameEntry]) -> dict[str, int]:
    """Count entries per classification method (label provenance)."""
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.method] = counts.get(e.method, 0) + 1
    return counts


def frame_manifest(
    entries: list[FrameEntry],
    *,
    tranco_list_id: str | None,
    tranco_source_url: str | None,
    cctld_source: str,
    generated_at: datetime | None = None,
) -> dict:
    """Build the reproducibility manifest for a frame (output metadata, not code).

    Records the exact inputs that produced the frame: the Tranco permanent list id
    and URL, the ccTLD-source description, the frontier ruleset version, and per-
    sector / per-method counts. Given the same list id + FRONTIER_VERSION, the frame
    is reproducible.
    """
    public_body = sum(1 for e in entries if e.is_public_body)
    return {
        "frontier_version": FRONTIER_VERSION,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "tranco_list_id": tranco_list_id,
        "tranco_source_url": tranco_source_url,
        "cctld_source": cctld_source,
        "total_domains": len(entries),
        "source_counts": _source_counts(entries),
        "sector_counts": sector_counts(entries),
        "method_counts": method_counts(entries),
        "is_public_body_count": public_body,
    }


def _source_counts(entries: Iterable[FrameEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.source] = counts.get(e.source, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Tranco list I/O (network) — thin, passive list download only
# ---------------------------------------------------------------------------
#
# This is list I/O, not scanning: it fetches a public ranking file. The domains in
# the frame are NOT contacted here (that is Sprint 2). A timeout is mandatory.

TRANCO_BASE = "https://tranco-list.eu"


def tranco_download_url(list_id: str, top: int | None = None) -> str:
    """Permanent Tranco download URL for a specific list id.

    ``/download/<id>/full`` returns the full ~1M list; ``/download/<id>/<N>`` the
    top N. Using a permanent list id (not the rolling ``top-1m.csv``) is what makes
    the frame reproducible.
    """
    tail = "full" if top is None else str(int(top))
    return f"{TRANCO_BASE}/download/{list_id}/{tail}"


def fetch_tranco_csv(
    list_id: str,
    dest: str | Path,
    *,
    top: int | None = None,
    timeout: float = 30.0,
    user_agent: str = "karne-frontier/0.1 (+https://github.com/ysfylcnky/karne)",
) -> Path:
    """Download a Tranco CSV to ``dest`` (raw list I/O). Returns the path.

    Passive: fetches one public file with an explicit timeout and never contacts the
    listed domains. The caller records ``list_id`` in the frame manifest.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = tranco_download_url(list_id, top=top)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https only)
        data = resp.read()
    dest.write_bytes(data)
    return dest


def read_tranco_csv(path: str | Path) -> Iterator[tuple[int, str]]:
    """Stream ``(rank, domain)`` rows from a Tranco CSV file on disk."""
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            parsed = parse_tranco_line(",".join(row))
            if parsed is not None:
                yield parsed
