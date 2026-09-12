"""Offline unit tests for the TLS/HTTP collector's pure parsers (dimension B).

No network: each parser is a function of its input, tested against hand-written
expected output (CLAUDE.md "expected output before code"). A live, network-marked
smoke test lives in tests/test_tls_http_network.py.
"""

from __future__ import annotations

from karne.collectors.tls_http import (
    _cert_fields,
    analyze_redirect_chain,
    parse_csp,
    parse_hsts,
    parse_security_txt,
    parse_set_cookie,
)

# --- HSTS ---


def test_parse_hsts_full():
    out = parse_hsts("max-age=31536000; includeSubDomains; preload")
    assert out == {
        "present": True,
        "raw": "max-age=31536000; includeSubDomains; preload",
        "max_age": 31536000,
        "include_subdomains": True,
        "preload": True,
    }


def test_parse_hsts_absent_and_malformed():
    assert parse_hsts(None) == {"present": False}
    out = parse_hsts("max-age=oops")
    assert out["present"] is True
    assert out["max_age"] is None
    assert out["include_subdomains"] is False


# --- CSP ---


def test_parse_csp_directives():
    out = parse_csp("default-src 'self'; script-src 'self' 'unsafe-inline'")
    assert out["present"] is True
    assert out["directives"]["default-src"] == ["'self'"]
    assert out["directives"]["script-src"] == ["'self'", "'unsafe-inline'"]


def test_parse_csp_absent():
    assert parse_csp(None) == {"present": False}


# --- Set-Cookie ---


def test_parse_set_cookie_attributes_only_no_value():
    cookies = parse_set_cookie(
        [
            "SID=SECRETVALUE; Path=/; Secure; HttpOnly; SameSite=Lax",
            "plain=x",
        ]
    )
    assert cookies[0] == {"name": "SID", "secure": True, "http_only": True, "samesite": "Lax"}
    assert cookies[1] == {"name": "plain", "secure": False, "http_only": False, "samesite": None}
    # The value is never recorded (no personal data).
    assert all("SECRETVALUE" not in str(c) for c in cookies)


# --- security.txt ---


def test_parse_security_txt_fields():
    body = "# comment\nContact: mailto:security@example.com\nExpires: 2027-01-01T00:00:00z\n"
    out = parse_security_txt(body)
    assert out["fields"]["contact"] == ["mailto:security@example.com"]
    assert out["fields"]["expires"] == ["2027-01-01T00:00:00z"]


# --- Redirect chain ---


def test_redirect_chain_clean_upgrade_to_https():
    hops = [
        {"url": "http://x.tr/", "scheme": "http", "host": "x.tr", "status": 301},
        {"url": "https://x.tr/", "scheme": "https", "host": "x.tr", "status": 200},
    ]
    out = analyze_redirect_chain(hops)
    assert out["reached_https"] is True
    assert out["cleartext_after_https"] is False
    assert out["host_changed"] is False


def test_redirect_chain_detects_cleartext_downgrade():
    # https then back to http = a cleartext step after encryption.
    hops = [
        {"url": "http://x.tr/", "scheme": "http", "host": "x.tr", "status": 302},
        {"url": "https://x.tr/a", "scheme": "https", "host": "x.tr", "status": 302},
        {"url": "http://x.tr/b", "scheme": "http", "host": "x.tr", "status": 200},
    ]
    out = analyze_redirect_chain(hops)
    assert out["cleartext_after_https"] is True
    assert out["reached_https"] is False


def test_redirect_chain_host_change():
    hops = [
        {"url": "http://x.tr/", "scheme": "http", "host": "x.tr", "status": 301},
        {"url": "https://www.y.tr/", "scheme": "https", "host": "www.y.tr", "status": 200},
    ]
    assert analyze_redirect_chain(hops)["host_changed"] is True


def test_redirect_chain_empty():
    out = analyze_redirect_chain([])
    assert out["reached_https"] is False
    assert out["final_scheme"] is None


# --- Certificate field extraction ---


def _cert(not_after: str, san: tuple[str, ...]) -> dict:
    return {
        "subject": ((("commonName", "example.com"),),),
        "issuer": ((("organizationName", "Let's Encrypt"),), (("commonName", "R3"),)),
        "notBefore": "Jan  1 00:00:00 2026 GMT",
        "notAfter": not_after,
        "subjectAltName": tuple(("DNS", h) for h in san),
    }


def test_cert_fields_extraction_and_exact_san_match():
    cert = _cert("Dec 31 23:59:59 2099 GMT", ("example.com", "www.example.com"))
    out = _cert_fields(cert, "example.com")
    assert out["issuer"] == "Let's Encrypt, R3"
    assert out["subject"] == "example.com"
    assert out["san"] == ["example.com", "www.example.com"]
    assert out["hostname_in_san"] is True
    assert out["not_after"] == "Dec 31 23:59:59 2099 GMT"
    assert out["days_remaining"] > 0


def test_cert_fields_wildcard_san_match_and_expiry_sign():
    out = _cert("Jan  1 00:00:00 2000 GMT", ("*.example.com",))
    fields = _cert_fields(out, "app.example.com")
    assert fields["hostname_in_san"] is True  # *.example.com matches app.example.com
    assert fields["days_remaining"] < 0  # already expired

    # Wildcard must not match the bare apex or a deeper label.
    assert _cert_fields(out, "example.com")["hostname_in_san"] is False
    assert _cert_fields(out, "a.b.example.com")["hostname_in_san"] is False
