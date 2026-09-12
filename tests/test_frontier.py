"""Offline unit tests for the Türkiye sample frame (Sprint 1).

No network access: the Tranco download is never called. Every test drives the pure
functions in ``karne.frontier`` with small in-memory fixtures. The frame is a list
producer, not a collector, so there is nothing to mock — only classification,
parsing and assembly logic to pin down.

Expected outputs are hand-written per CLAUDE.md ("expected output before code"):
the danger in this layer is a silent mislabel, so the five known target domains and
the honest "unknown" case are asserted explicitly.
"""

from __future__ import annotations

from karne import frontier as f

# ---------------------------------------------------------------------------
# .tr detection
# ---------------------------------------------------------------------------


def test_is_dot_tr_true_for_tr_domains():
    assert f.is_dot_tr("itu.edu.tr")
    assert f.is_dot_tr("turkiye.gov.tr")
    assert f.is_dot_tr("example.tr")


def test_is_dot_tr_false_for_non_tr():
    assert not f.is_dot_tr("mumifashion.com")
    assert not f.is_dot_tr("example.com")
    # ".tr" must be a real label boundary, not a substring of the last label.
    assert not f.is_dot_tr("mytr.com")
    assert not f.is_dot_tr("host.metr")


def test_tr_second_level_extracts_sld():
    assert f.tr_second_level("itu.edu.tr") == "edu"
    assert f.tr_second_level("turkiye.gov.tr") == "gov"
    assert f.tr_second_level("garantibbva.com.tr") == "com"
    # Subdomains still resolve to the second level.
    assert f.tr_second_level("www.itu.edu.tr") == "edu"


def test_tr_second_level_none_cases():
    assert f.tr_second_level("example.com") is None  # not .tr
    assert f.tr_second_level("example.tr") is None  # bare 2-label .tr


# ---------------------------------------------------------------------------
# classify_sector — the five known targets (hand-written expected output)
# ---------------------------------------------------------------------------


def test_classify_universities_by_tld_rule():
    for domain in ("itu.edu.tr", "istanbul.edu.tr"):
        c = f.classify_sector(domain)
        assert c.sector == f.SECTOR_UNIVERSITY
        assert c.is_public_body is True
        assert c.method == f.METHOD_TLD_RULE
        assert c.evidence == "edu.tr"


def test_classify_public_body_by_tld_rule():
    c = f.classify_sector("turkiye.gov.tr")
    assert c.sector == f.SECTOR_PUBLIC_BODY
    assert c.is_public_body is True
    assert c.method == f.METHOD_TLD_RULE


def test_classify_bank_by_seed_list():
    c = f.classify_sector("garantibbva.com.tr")
    assert c.sector == f.SECTOR_BANK
    assert c.is_public_body is False
    assert c.method == f.METHOD_SEED_LIST


def test_classify_ecommerce_curated_com():
    c = f.classify_sector("mumifashion.com")
    assert c.sector == f.SECTOR_ECOMMERCE
    assert c.is_public_body is False
    assert c.method == f.METHOD_SEED_LIST


# ---------------------------------------------------------------------------
# classify_sector — other rules and the honest "unknown"
# ---------------------------------------------------------------------------


def test_classify_municipality_by_tld_rule():
    c = f.classify_sector("ankara.bel.tr")
    assert c.sector == f.SECTOR_MUNICIPALITY
    assert c.is_public_body is True
    assert c.method == f.METHOD_TLD_RULE


def test_classify_unknown_is_not_forced():
    # A commercial .tr domain with no seed/keyword signal stays unknown — the
    # honest "unsure" case, distinct from "not Turkish" (which is exclusion).
    c = f.classify_sector("randomcompany.com.tr")
    assert c.sector == f.SECTOR_UNKNOWN
    assert c.is_public_body is False
    assert c.method == f.METHOD_NONE
    assert c.evidence is None


def test_classify_keyword_municipality():
    c = f.classify_sector("bandirmabelediye.com.tr")
    assert c.sector == f.SECTOR_MUNICIPALITY
    assert c.is_public_body is True
    assert c.method == f.METHOD_KEYWORD
    assert c.evidence == "keyword:belediye"


def test_classify_keyword_hospital_not_public_body():
    c = f.classify_sector("ozelhastane.com.tr")
    assert c.sector == f.SECTOR_HOSPITAL
    assert c.is_public_body is False
    assert c.method == f.METHOD_KEYWORD


def test_seed_list_wins_over_tld_rule_precedence():
    # A domain present in a seed list is classified by the seed even though its
    # .tr TLD carries no rule; seed precedence is highest.
    c = f.classify_sector("hurriyet.com.tr")
    assert c.sector == f.SECTOR_MEDIA
    assert c.method == f.METHOD_SEED_LIST


def test_classify_normalizes_input():
    # Trailing dot, whitespace and case are normalised before matching.
    c = f.classify_sector("  ITU.EDU.TR.  ")
    assert c.sector == f.SECTOR_UNIVERSITY
    assert c.method == f.METHOD_TLD_RULE


def test_curated_tr_com_are_all_generic_tld():
    # The expansion set must never contain .tr domains (those are the core tier).
    assert f.CURATED_TR_COM  # non-empty
    assert all(not f.is_dot_tr(d) for d in f.CURATED_TR_COM)


# ---------------------------------------------------------------------------
# Tranco line parsing
# ---------------------------------------------------------------------------


def test_parse_tranco_line_ok():
    assert f.parse_tranco_line("1,google.com") == (1, "google.com")
    assert f.parse_tranco_line("42,ITU.EDU.TR") == (42, "itu.edu.tr")


def test_parse_tranco_line_normalizes_trailing_dot_and_space():
    assert f.parse_tranco_line("  7 , Example.Tr. ") == (7, "example.tr")


def test_parse_tranco_line_rejects_malformed():
    assert f.parse_tranco_line("") is None
    assert f.parse_tranco_line("   ") is None
    assert f.parse_tranco_line("nodomain") is None  # single field
    assert f.parse_tranco_line("notarank,example.com") is None  # non-int rank
    assert f.parse_tranco_line("5,") is None  # empty domain


def test_parse_tranco_rows_skips_bad_lines():
    lines = ["1,a.com", "garbage", "", "2,b.edu.tr", "x,y,z"]
    rows = list(f.parse_tranco_rows(lines))
    # "x,y,z" parses (rank x is non-int -> skipped); a.com and b.edu.tr survive.
    assert rows == [(1, "a.com"), (2, "b.edu.tr")]


# ---------------------------------------------------------------------------
# build_frame
# ---------------------------------------------------------------------------


def _sample_rows():
    # Mixed list: .tr (kept), generic non-curated .com (dropped), and a curated
    # .com that also ranks in Tranco (kept, rank backfilled).
    return [
        (1, "trendyol.com"),  # curated ecommerce, also in Tranco
        (2, "google.com"),  # non-Turkish generic -> excluded
        (3, "itu.edu.tr"),  # university via TLD rule
        (4, "garantibbva.com.tr"),  # bank via seed
        (5, "randomcompany.com.tr"),  # unknown .tr
        (6, "notturkish.com"),  # generic, not curated -> excluded
    ]


def test_build_frame_keeps_tr_and_curated_only():
    frame = f.build_frame(_sample_rows())
    domains = {e.domain for e in frame}
    # .tr domains kept; curated .com kept; non-curated generic dropped.
    assert "itu.edu.tr" in domains
    assert "garantibbva.com.tr" in domains
    assert "randomcompany.com.tr" in domains
    assert "trendyol.com" in domains
    assert "google.com" not in domains
    assert "notturkish.com" not in domains
    # mumifashion.com is curated but absent from the sample rows -> added anyway.
    assert "mumifashion.com" in domains


def test_build_frame_sources_and_ranks():
    frame = {e.domain: e for e in f.build_frame(_sample_rows())}
    assert frame["itu.edu.tr"].source == f.SOURCE_TRANCO
    assert frame["itu.edu.tr"].rank == 3
    # Curated domain that appeared in Tranco keeps its rank but is marked curated.
    assert frame["trendyol.com"].source == f.SOURCE_CURATED_TR_COM
    assert frame["trendyol.com"].rank == 1
    # Curated domain absent from Tranco has no rank.
    assert frame["mumifashion.com"].source == f.SOURCE_CURATED_TR_COM
    assert frame["mumifashion.com"].rank is None


def test_build_frame_without_curated():
    frame = {e.domain for e in f.build_frame(_sample_rows(), include_curated=False)}
    assert "mumifashion.com" not in frame  # curated set omitted
    assert "trendyol.com" not in frame  # only .tr survives Pass A
    assert "itu.edu.tr" in frame


def test_build_frame_dedup_and_order():
    rows = [(10, "b.edu.tr"), (2, "a.gov.tr"), (10, "b.edu.tr")]
    frame = f.build_frame(rows, include_curated=False)
    domains = [e.domain for e in frame]
    assert domains.count("b.edu.tr") == 1  # de-duplicated
    assert domains.index("a.gov.tr") < domains.index("b.edu.tr")  # ranked order


def test_build_frame_dedup_keeps_smallest_rank():
    frame = {
        e.domain: e
        for e in f.build_frame([(50, "x.edu.tr"), (5, "x.edu.tr")], include_curated=False)
    }
    assert frame["x.edu.tr"].rank == 5


# ---------------------------------------------------------------------------
# Counts and manifest
# ---------------------------------------------------------------------------


def test_sector_counts_zero_fills_all_sectors():
    frame = f.build_frame(_sample_rows())
    counts = f.sector_counts(frame)
    assert set(counts) == set(f.SECTORS)  # every sector present
    assert counts[f.SECTOR_UNIVERSITY] >= 1
    assert counts[f.SECTOR_UNKNOWN] >= 1
    assert sum(counts.values()) == len(frame)


def test_method_counts_sum_to_total():
    frame = f.build_frame(_sample_rows())
    counts = f.method_counts(frame)
    assert sum(counts.values()) == len(frame)


def test_frame_manifest_records_provenance():
    frame = f.build_frame(_sample_rows())
    man = f.frame_manifest(
        frame,
        tranco_list_id="ABCDE",
        tranco_source_url="https://tranco-list.eu/download/ABCDE/full",
        cctld_source="Tranco .tr subset + curated_tr_com",
    )
    assert man["frontier_version"] == f.FRONTIER_VERSION
    assert man["tranco_list_id"] == "ABCDE"
    assert man["total_domains"] == len(frame)
    assert man["sector_counts"] == f.sector_counts(frame)
    assert man["source_counts"][f.SOURCE_CURATED_TR_COM] >= 1
    assert "generated_at" in man


def test_tranco_download_url_forms():
    assert f.tranco_download_url("ABCDE") == "https://tranco-list.eu/download/ABCDE/full"
    assert f.tranco_download_url("ABCDE", top=1000) == "https://tranco-list.eu/download/ABCDE/1000"
