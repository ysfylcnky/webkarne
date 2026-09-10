"""Offline unit tests for the DNS/email collector.

No network access: DNS answers are supplied through a fake client / canned
fixtures, and the exception->status mapping of the real DnsClient is exercised
by injecting a fake resolver. Live-network tests live in
tests/test_dns_email_network.py and are marked ``network``.
"""

from __future__ import annotations

import base64

import dns.exception
import dns.resolver
import pytest

from karne.collectors import dns_email as de
from karne.collectors.dns_email import (
    DnsClient,
    DnsQuery,
    classify_mx_provider,
    collect_dkim,
    collect_dmarc,
    collect_dnssec,
    collect_mx,
    collect_spf,
    count_spf_lookups,
    parse_dkim_record,
    parse_dmarc_record,
    parse_spf_record,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeDnsClient:
    """Stand-in for DnsClient: returns canned DnsQuery objects, logs queries.

    ``responses`` maps (name, rtype) -> dict(status=, answers=, authenticated=).
    A missing key defaults to NXDOMAIN (name does not exist).
    """

    def __init__(self, responses: dict[tuple[str, str], dict] | None = None) -> None:
        self.responses = responses or {}
        self.nameservers = ["203.0.113.53"]
        self.queries: list[DnsQuery] = []

    def resolve(self, name: str, rtype: str) -> DnsQuery:
        spec = self.responses.get((name, rtype))
        if spec is None:
            query = DnsQuery(
                name,
                rtype,
                "nxdomain",
                "2026-01-01T00:00:00+00:00",
                self.nameservers,
                rcode="NXDOMAIN",
            )
        else:
            query = DnsQuery(
                name,
                rtype,
                spec.get("status", "ok"),
                "2026-01-01T00:00:00+00:00",
                self.nameservers,
                answers=list(spec.get("answers", [])),
                rcode=spec.get("rcode"),
                authenticated=spec.get("authenticated"),
                error_detail=spec.get("error_detail"),
            )
        self.queries.append(query)
        return query


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der_tlv(tag: int, val: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(val)) + val


def _der_int(val: bytes) -> bytes:
    if val[0] & 0x80:  # positive integer with high bit set needs a leading 0x00
        val = b"\x00" + val
    return _der_tlv(0x02, val)


def rsa_spki_b64(modulus_bytes: bytes) -> str:
    """Build a DER SubjectPublicKeyInfo for an RSA key and base64-encode it."""
    rsa_pub = _der_tlv(0x30, _der_int(modulus_bytes) + _der_int((65537).to_bytes(3, "big")))
    algo = _der_tlv(0x30, _der_tlv(0x06, bytes.fromhex("2a864886f70d010101")) + _der_tlv(0x05, b""))
    bitstr = _der_tlv(0x03, b"\x00" + rsa_pub)
    return base64.b64encode(_der_tlv(0x30, algo + bitstr)).decode()


# ===========================================================================
# SPF
# ===========================================================================


def test_spf_plus_all_terminator():
    parsed = parse_spf_record("v=spf1 include:_spf.example.com +all")
    assert parsed["version_ok"] is True
    assert parsed["terminator"] == {
        "qualifier": "+",
        "type": "all",
        "value": None,
        "raw": "+all",
    }


def test_spf_terminator_variants():
    for token, qualifier in [("-all", "-"), ("~all", "~"), ("?all", "?"), ("all", "+")]:
        parsed = parse_spf_record(f"v=spf1 {token}")
        assert parsed["terminator"]["qualifier"] == qualifier


def test_spf_counts_local_lookup_terms():
    parsed = parse_spf_record("v=spf1 a mx include:x.example ip4:1.2.3.4 exists:%{i}.example -all")
    # a, mx, include, exists = 4 lookup terms; ip4 and all do not count.
    assert parsed["lookup_terms_here"] == 4


def test_spf_multiple_records_is_flagged():
    domain = "multi-spf.example"
    client = FakeDnsClient(
        {(domain, "TXT"): {"answers": ["v=spf1 include:a.example -all", "v=spf1 -all"]}}
    )
    result = collect_spf(domain, client)
    assert result["present"] is True
    assert result["multiple"] is True
    assert isinstance(result["parsed"], list) and len(result["parsed"]) == 2
    assert "lookups" not in result  # chain is not counted for an invalid multi-record set


def test_spf_chain_within_limit():
    root = "v=spf1 include:a.example include:b.example -all"
    records = {
        "a.example": "v=spf1 ip4:1.0.0.0/8 -all",
        "b.example": "v=spf1 include:c.example -all",
        "c.example": "v=spf1 ip4:2.0.0.0/8 -all",
    }
    fetch = lambda n: {"record": records.get(n), "status": "ok" if n in records else "nxdomain"}  # noqa: E731
    result = count_spf_lookups(root, fetch)
    # root: 2 includes; b: 1 include; = 3 lookups total.
    assert result["total_lookups"] == 3
    assert result["exceeds_limit"] is False


def test_spf_chain_exceeds_limit():
    includes = " ".join(f"include:i{n}.example" for n in range(11))
    root = f"v=spf1 {includes} -all"
    fetch = lambda n: {"record": "v=spf1 -all", "status": "ok"}  # noqa: E731 - every leaf is terminal
    result = count_spf_lookups(root, fetch)
    assert result["total_lookups"] == 11
    assert result["exceeds_limit"] is True


def test_spf_loop_detected_without_recursion_error():
    root = "v=spf1 include:self.example -all"
    fetch = lambda n: {"record": "v=spf1 include:self.example -all", "status": "ok"}  # noqa: E731
    result = count_spf_lookups(root, fetch)
    assert result["loop_detected"] is True  # must not hang or raise


def test_spf_include_failure_recorded_in_chain():
    root = "v=spf1 include:broken.example -all"
    fetch = lambda n: {"record": None, "status": "timeout"}  # noqa: E731
    result = count_spf_lookups(root, fetch)
    failed = [s for s in result["chain"] if s.get("record") is None]
    assert failed and failed[0]["status"] == "timeout"


# ===========================================================================
# DMARC
# ===========================================================================


def test_dmarc_p_none_valid():
    parsed = parse_dmarc_record("v=DMARC1; p=none; rua=mailto:agg@example.com")
    assert parsed["p"] == "none"
    assert parsed["valid"] is True
    assert parsed["has_aggregate_reporting"] is True


def test_dmarc_without_rua():
    parsed = parse_dmarc_record("v=DMARC1; p=reject")
    assert parsed["valid"] is True  # rua is not required for syntactic validity
    assert parsed["rua"] is None
    assert parsed["has_aggregate_reporting"] is False


def test_dmarc_malformed_is_invalid():
    parsed = parse_dmarc_record("this is not dmarc")
    assert parsed["valid"] is False
    assert "missing_or_misplaced_version" in parsed["issues"]
    assert "missing_policy" in parsed["issues"]


def test_dmarc_invalid_policy_and_pct():
    parsed = parse_dmarc_record("v=DMARC1; p=bogus; pct=abc")
    assert parsed["valid"] is False
    assert "invalid_policy_value" in parsed["issues"]
    assert "pct_not_integer" in parsed["issues"]


def test_dmarc_version_not_first_is_invalid():
    parsed = parse_dmarc_record("p=reject; v=DMARC1")
    assert parsed["valid"] is False
    assert "missing_or_misplaced_version" in parsed["issues"]


# ===========================================================================
# DKIM
# ===========================================================================


def test_dkim_rsa_key_bits():
    for bits, top in [(2048, 256), (1024, 128)]:
        modulus = b"\x80" + b"\x00" * (top - 1)  # `top` bytes, high bit set
        record = f"v=DKIM1; k=rsa; p={rsa_spki_b64(modulus)}"
        assert parse_dkim_record(record)["key_bits"] == bits


def test_dkim_empty_p_is_revoked():
    parsed = parse_dkim_record("v=DKIM1; k=rsa; p=")
    assert parsed["p_present"] is True
    assert parsed["p_empty"] is True
    assert parsed["key_bits"] is None


def test_dkim_ed25519_key_bits():
    key = base64.b64encode(b"\x01" * 32).decode()  # 32-byte raw ed25519 key
    parsed = parse_dkim_record(f"v=DKIM1; k=ed25519; p={key}")
    assert parsed["key_type"] == "ed25519"
    assert parsed["key_bits"] == 256


def test_dkim_collector_selector_guessing_method():
    domain = "dkim.example"
    client = FakeDnsClient(
        {("selector1._domainkey.dkim.example", "TXT"): {"answers": ["v=DKIM1; k=rsa; p="]}}
    )
    result = collect_dkim(domain, client, ["selector1", "google", "mail"])
    assert result["method"] == "selector_guessing"
    assert result["found_selectors"] == ["selector1"]
    entry = next(a for a in result["attempts"] if a["selector"] == "selector1")
    assert entry["parsed"]["p_empty"] is True


# ===========================================================================
# MX
# ===========================================================================


def test_mx_provider_classification():
    mapping = {"google.com": "google", "outlook.com": "microsoft"}
    assert classify_mx_provider("aspmx.l.google.com.", "example.com", mapping) == "google"
    assert classify_mx_provider("mail.example.com.", "example.com", mapping) == "local"
    assert classify_mx_provider("mx.unknownhost.io.", "example.com", mapping) == "other"


def test_mx_absent_domain():
    domain = "no-mx.example"
    client = FakeDnsClient({(domain, "MX"): {"status": "noanswer", "answers": []}})
    result = collect_mx(domain, client, {})
    assert result["present"] is False
    assert result["records"] == []
    assert result["query"]["status"] == "noanswer"  # distinct from a failed query


def test_mx_records_sorted_by_preference():
    domain = "mx.example"
    client = FakeDnsClient(
        {(domain, "MX"): {"answers": ["20 alt.mail.example.com.", "10 mail.example.com."]}}
    )
    result = collect_mx(domain, client, {})
    assert [r["preference"] for r in result["records"]] == [10, 20]


# ===========================================================================
# DNSSEC
# ===========================================================================


def test_dnssec_present():
    domain = "signed.example"
    client = FakeDnsClient(
        {(domain, "DS"): {"answers": ["12345 13 2 ABCD"], "authenticated": True}}
    )
    result = collect_dnssec(domain, client)
    assert result["ds_present"] is True
    assert result["resolver_authenticated"] is True


def test_dnssec_absent():
    domain = "unsigned.example"
    client = FakeDnsClient({(domain, "DS"): {"status": "noanswer", "answers": []}})
    result = collect_dnssec(domain, client)
    assert result["ds_present"] is False


# ===========================================================================
# Rule 6 — failures must stay distinct from "no record"
# ===========================================================================


@pytest.mark.parametrize("status", ["timeout", "servfail", "error"])
def test_query_failures_not_treated_as_no_record(status):
    # A failed query must surface its failure status, never be silently turned
    # into "no DMARC record present".
    domain = "fails.example"
    client = FakeDnsClient({(f"_dmarc.{domain}", "TXT"): {"status": status, "answers": []}})
    result = collect_dmarc(domain, client)
    assert result["present"] is False
    assert result["query"]["status"] == status


def test_nxdomain_and_noanswer_are_distinct():
    # Both mean "no record", but they are different DNS facts and stay distinct.
    domain_nx = "nx.example"
    domain_nodata = "nodata.example"
    nx = collect_dmarc(domain_nx, FakeDnsClient())  # missing -> nxdomain
    nodata = collect_dmarc(
        domain_nodata, FakeDnsClient({(f"_dmarc.{domain_nodata}", "TXT"): {"status": "noanswer"}})
    )
    assert nx["query"]["status"] == "nxdomain"
    assert nodata["query"]["status"] == "noanswer"


# ===========================================================================
# Real DnsClient exception -> status mapping (fake resolver, no network)
# ===========================================================================


class _FakeResolver:
    """Minimal resolver whose resolve() always raises ``exc`` (counts calls)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def resolve(self, name, rtype, raise_on_no_answer=True):
        self.calls += 1
        raise self._exc


def _client_with(exc: Exception, retries: int = 0) -> tuple[DnsClient, _FakeResolver]:
    client = DnsClient(
        {
            "retries": retries,
            "retry_backoff_seconds": 0,
            "rate_per_second": 0,
            "timeout_seconds": 0.1,
            "lifetime_seconds": 0.1,
        }
    )
    fake = _FakeResolver(exc)
    client._resolver = fake
    return client, fake


def test_client_maps_nxdomain():
    client, _ = _client_with(dns.resolver.NXDOMAIN())
    assert client.resolve("x.example", "TXT").status == "nxdomain"


def test_client_maps_noanswer():
    client, _ = _client_with(dns.resolver.NoAnswer())
    assert client.resolve("x.example", "TXT").status == "noanswer"


def test_client_maps_timeout_and_retries():
    client, fake = _client_with(dns.exception.Timeout(), retries=2)
    query = client.resolve("x.example", "TXT")
    assert query.status == "timeout"
    assert fake.calls == 3  # initial try + 2 retries


def test_client_maps_servfail():
    exc = dns.resolver.NoNameservers("All nameservers failed; server answered SERVFAIL")
    client, _ = _client_with(exc)
    # NoNameservers carrying SERVFAIL maps to servfail, not a generic error.
    assert client.resolve("x.example", "TXT").status == "servfail"


def test_client_never_raises_on_unexpected_error():
    client, _ = _client_with(RuntimeError("boom"))
    query = client.resolve("x.example", "TXT")
    assert query.status == "error"
    assert "RuntimeError" in query.error_detail


# ===========================================================================
# Settings & helpers
# ===========================================================================


def test_normalize_domain():
    assert de.normalize_domain("  Example.COM.  ") == "example.com"


def test_load_settings_has_expected_sections():
    settings = de.load_settings()
    assert "dns" in settings and "dkim" in settings and "mx_providers" in settings
    assert isinstance(settings["dkim"]["selectors"], list) and settings["dkim"]["selectors"]
