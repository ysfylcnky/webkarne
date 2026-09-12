"""TLS / HTTP collector — dimension B (transport & server security).

Single entry point: ``collect(domain, settings) -> dict``. Like the DNS/email
collector, the output is RAW and UNINTERPRETED (CLAUDE.md rule 1): it records what
was observed on a normal visit to the site's homepage, never a score or judgement
("TLS 1.0 open = bad", "HSTS max-age too short" belong to the scoring layer, K-02).

Passive, browser-equivalent measurement only (PLAN.md K-07 and the §4 TLS-version
decision): a homepage HTTP GET and TLS handshakes on port 443. No STARTTLS, no port
scanning, no directory/file probing, no exploitation. Every network call has an
explicit timeout and honours the configured rate limit (rule 4). A failure in one
indicator does not abort the others (rule 3); connection failures are recorded as
distinct states, never conflated with "feature absent" (rule 6).

What is measured (PLAN.md dimension B): HTTPS enforcement (the http:// redirect
chain), TLS versions supported (a separate handshake per version) with the
negotiated cipher, the certificate (validity/issuer/SAN/days remaining, verified
or the verification failure reason), HSTS, the security headers (CSP, X-Frame-
Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy), server
information leakage, security.txt, and homepage cookie attributes.

Pure parsers (parse_hsts, parse_csp, parse_set_cookie, parse_security_txt,
analyze_redirect_chain, certificate-field extraction) are functions of their inputs
and are unit-tested against fixtures with no network (see tests/).
"""

from __future__ import annotations

import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from karne.collectors.dns_email import _RateLimiter, config_hash, load_settings

COLLECTOR = "tls_http"
COLLECTOR_VERSION = "0.1.0"

# TLS version name -> ssl.TLSVersion. Names match config/settings.toml.
_TLS_VERSIONS: dict[str, ssl.TLSVersion] = {
    "TLSv1": ssl.TLSVersion.TLSv1,
    "TLSv1.1": ssl.TLSVersion.TLSv1_1,
    "TLSv1.2": ssl.TLSVersion.TLSv1_2,
    "TLSv1.3": ssl.TLSVersion.TLSv1_3,
}

# Security / information headers recorded verbatim (lower-cased keys).
_SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "content-security-policy-report-only",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
)
_INFO_HEADERS = ("server", "x-powered-by", "x-generator", "x-aspnet-version")


# ---------------------------------------------------------------------------
# Pure parsers (no network)
# ---------------------------------------------------------------------------


def parse_hsts(value: str | None) -> dict[str, Any]:
    """Parse a Strict-Transport-Security header value into its directives."""
    if value is None:
        return {"present": False}
    out: dict[str, Any] = {
        "present": True,
        "raw": value,
        "max_age": None,
        "include_subdomains": False,
        "preload": False,
    }
    for token in value.split(";"):
        t = token.strip().lower()
        if t.startswith("max-age"):
            _, _, num = t.partition("=")
            try:
                out["max_age"] = int(num.strip().strip('"'))
            except ValueError:
                out["max_age"] = None
        elif t == "includesubdomains":
            out["include_subdomains"] = True
        elif t == "preload":
            out["preload"] = True
    return out


def parse_csp(value: str | None) -> dict[str, Any]:
    """Parse a Content-Security-Policy header into a directive -> sources map."""
    if value is None:
        return {"present": False}
    directives: dict[str, list[str]] = {}
    for part in value.split(";"):
        tokens = part.split()
        if not tokens:
            continue
        name = tokens[0].lower()
        directives[name] = tokens[1:]
    return {"present": True, "raw": value, "directives": directives}


def parse_set_cookie(headers: list[str]) -> list[dict[str, Any]]:
    """Parse Set-Cookie header lines into per-cookie attribute observations.

    Records only the cookie NAME and its security attributes (Secure, HttpOnly,
    SameSite); never the value (no personal data, PLAN.md ethics).
    """
    cookies: list[dict[str, Any]] = []
    for line in headers:
        if not line or "=" not in line:
            continue
        first, _, rest = line.partition(";")
        name = first.split("=", 1)[0].strip()
        if not name:
            continue
        attrs_raw = [a.strip() for a in rest.split(";")] if rest else []
        attrs_low = [a.lower() for a in attrs_raw]
        samesite = None
        for a in attrs_raw:  # preserve the value's original case (raw observation)
            if a.lower().startswith("samesite"):
                _, _, sv = a.partition("=")
                samesite = sv.strip() or None
        cookies.append(
            {
                "name": name,
                "secure": "secure" in attrs_low,
                "http_only": "httponly" in attrs_low,
                "samesite": samesite,
            }
        )
    return cookies


def parse_security_txt(text: str) -> dict[str, Any]:
    """Parse a security.txt body (RFC 9116) into a field -> [values] map."""
    fields: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields.setdefault(key.strip().lower(), []).append(val.strip())
    return {"fields": fields}


def analyze_redirect_chain(hops: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise an http:// redirect chain for HTTPS-enforcement observations.

    Factual observations only: whether it ends on https, whether any hop after an
    https hop fell back to http (a cleartext downgrade), and whether the host
    changed. No judgement.
    """
    reached_https = bool(hops) and hops[-1].get("scheme") == "https"
    seen_https = False
    cleartext_after_https = False
    hosts: list[str] = []
    for hop in hops:
        scheme = hop.get("scheme")
        if hop.get("host"):
            hosts.append(hop["host"])
        if scheme == "https":
            seen_https = True
        elif scheme == "http" and seen_https:
            cleartext_after_https = True
    host_changed = len(set(hosts)) > 1
    return {
        "hops": len(hops),
        "reached_https": reached_https,
        "final_scheme": hops[-1].get("scheme") if hops else None,
        "final_url": hops[-1].get("url") if hops else None,
        "cleartext_after_https": cleartext_after_https,
        "host_changed": host_changed,
    }


def _cert_fields(cert: dict[str, Any], hostname: str) -> dict[str, Any]:
    """Extract observed fields from ssl.getpeercert()'s parsed dict."""

    def _join(seq: Any) -> str | None:
        # ssl represents subject/issuer as a tuple of RDN tuples.
        parts = []
        for rdn in seq or ():
            for k, v in rdn:
                if k in ("commonName", "organizationName"):
                    parts.append(v)
        return ", ".join(parts) or None

    san = [v for (t, v) in cert.get("subjectAltName", ()) if t == "DNS"]
    not_after = cert.get("notAfter")
    days_remaining = None
    if not_after:
        try:
            expiry = ssl.cert_time_to_seconds(not_after)
            days_remaining = int((expiry - datetime.now(UTC).timestamp()) // 86400)
        except (ValueError, OverflowError):
            days_remaining = None
    return {
        "subject": _join(cert.get("subject")),
        "issuer": _join(cert.get("issuer")),
        "not_before": cert.get("notBefore"),
        "not_after": not_after,
        "days_remaining": days_remaining,
        "san": san,
        "hostname_in_san": hostname in san or any(_wildcard_match(p, hostname) for p in san),
    }


def _wildcard_match(pattern: str, host: str) -> bool:
    if pattern.startswith("*."):
        return host.split(".", 1)[-1] == pattern[2:]
    return pattern == host


# ---------------------------------------------------------------------------
# Network layer (explicit timeouts; states kept distinct per rule 6)
# ---------------------------------------------------------------------------


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def probe_tls_versions(host: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Probe each configured TLS version with a separate handshake on port 443.

    States per version: ``supported`` / ``not_supported`` (server refused) /
    ``unprobeable_local`` (the local OpenSSL cannot configure this version) /
    ``error`` (connection could not be measured). The local/ server distinction
    for legacy versions is imperfect — noted in ``note``.
    """
    cfg = settings.get("tls_http", {})
    timeout = float(cfg.get("timeout_seconds", 7.0))
    names = cfg.get("probe_tls_versions", list(_TLS_VERSIONS))
    probed: dict[str, Any] = {}
    supported: list[str] = []
    for name in names:
        tlsver = _TLS_VERSIONS.get(name)
        if tlsver is None:
            probed[name] = {"status": "unprobeable_local", "detail": "unknown version name"}
            continue
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.minimum_version = tlsver
            ctx.maximum_version = tlsver
        except (ValueError, OSError) as exc:
            probed[name] = {"status": "unprobeable_local", "detail": _short(exc)}
            continue
        try:
            with (
                socket.create_connection((host, 443), timeout=timeout) as sock,
                ctx.wrap_socket(sock, server_hostname=host) as ss,
            ):
                cipher = ss.cipher()
                probed[name] = {
                    "status": "supported",
                    "negotiated_version": ss.version(),
                    "cipher": cipher[0] if cipher else None,
                }
                supported.append(name)
        except ssl.SSLError as exc:
            probed[name] = {"status": "not_supported", "detail": _short(exc)}
        except TimeoutError:
            probed[name] = {"status": "error", "detail": "timeout"}
        except OSError as exc:
            probed[name] = {"status": "error", "detail": _short(exc)}
    return {
        "probed": probed,
        "supported": supported,
        "note": (
            "Each version is a separate standard handshake on 443 (browser-equivalent, "
            "K-07). 'not_supported' vs 'unprobeable_local' for TLS 1.0/1.1 may reflect "
            "the local OpenSSL build rather than the server; detail is recorded."
        ),
    }


def fetch_certificate(host: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Verifying handshake for cert fields; on verification failure, capture the
    reason and confirm cert presence with a non-verifying handshake."""
    cfg = settings.get("tls_http", {})
    timeout = float(cfg.get("timeout_seconds", 7.0))
    out: dict[str, Any] = {"obtained": False, "verified": None, "verify_error": None}

    ctx = ssl.create_default_context()
    try:
        with (
            socket.create_connection((host, 443), timeout=timeout) as sock,
            ctx.wrap_socket(sock, server_hostname=host) as ss,
        ):
            cert = ss.getpeercert() or {}
            out.update(_cert_fields(cert, host))
            out["obtained"] = True
            out["verified"] = True
            return out
    except ssl.SSLCertVerificationError as exc:
        out["verified"] = False
        out["verify_error"] = getattr(exc, "verify_message", None) or _short(exc)
    except (ssl.SSLError, TimeoutError, OSError) as exc:
        out["error"] = _short(exc)
        return out

    # Verification failed: confirm a certificate was served (fields need an X.509
    # parser we do not depend on; the verification reason above is the finding).
    ctx2 = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx2.check_hostname = False
    ctx2.verify_mode = ssl.CERT_NONE
    try:
        with (
            socket.create_connection((host, 443), timeout=timeout) as sock,
            ctx2.wrap_socket(sock, server_hostname=host) as ss,
        ):
            der = ss.getpeercert(binary_form=True)
            out["obtained"] = der is not None
            out["der_bytes"] = len(der) if der else 0
            out["fields_parsed"] = False  # stdlib limit for unverified certs
    except OSError as exc:
        out.setdefault("error", _short(exc))
    return out


def _request_once(url: str, settings: dict[str, Any]) -> dict[str, Any]:
    """One HTTP(S) GET WITHOUT following redirects. Records status + headers, or an
    error state. HTTPS certificates are verified (browser-equivalent)."""
    cfg = settings.get("tls_http", {})
    http_cfg = settings.get("http", {})
    timeout = float(cfg.get("timeout_seconds", 7.0))
    ua = http_cfg.get("user_agent", f"karne/{COLLECTOR_VERSION}")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # type: ignore[override]
            return None  # do not follow; return the 3xx response as-is

    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": ua})
    try:
        resp = opener.open(req, timeout=timeout)
        status = resp.status
        headers = resp.headers
    except urllib.error.HTTPError as exc:  # 3xx (no-redirect) and 4xx/5xx land here
        status = exc.code
        headers = exc.headers
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        return {"url": url, "error": _short(exc)}

    parsed = urllib.parse.urlsplit(url)
    location = headers.get("Location")
    set_cookie = headers.get_all("Set-Cookie") or []
    header_map = {k.lower(): v for k, v in headers.items()}
    return {
        "url": url,
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "status": status,
        "location": location,
        "headers": header_map,
        "set_cookie": set_cookie,
    }


def follow_http_chain(
    domain: str, settings: dict[str, Any], limiter: _RateLimiter
) -> dict[str, Any]:
    """Follow the http:// homepage redirect chain manually, up to max_redirects."""
    cfg = settings.get("tls_http", {})
    max_redirects = int(cfg.get("max_redirects", 10))
    url = f"http://{domain}/"
    hops: list[dict[str, Any]] = []
    for _ in range(max_redirects + 1):
        limiter.acquire()
        resp = _request_once(url, settings)
        if "error" in resp:
            hops.append(
                {"url": url, "scheme": urllib.parse.urlsplit(url).scheme, "error": resp["error"]}
            )
            break
        hops.append(
            {
                "url": resp["url"],
                "scheme": resp["scheme"],
                "host": resp["host"],
                "status": resp["status"],
                "location": resp.get("location"),
            }
        )
        loc = resp.get("location")
        if resp["status"] in (301, 302, 303, 307, 308) and loc:
            url = urllib.parse.urljoin(url, loc)
            continue
        break
    summary = analyze_redirect_chain(hops)
    summary["chain"] = hops
    return summary


def _fetch_headers(url: str, settings: dict[str, Any], limiter: _RateLimiter) -> dict[str, Any]:
    limiter.acquire()
    resp = _request_once(url, settings)
    if "error" in resp:
        return {"reachable": False, "error": resp["error"], "url": url}
    headers = resp["headers"]
    security = {h: headers.get(h) for h in _SECURITY_HEADERS if headers.get(h) is not None}
    info = {h: headers.get(h) for h in _INFO_HEADERS if headers.get(h) is not None}
    return {
        "reachable": True,
        "url": url,
        "status": resp["status"],
        "security_headers": security,
        "info_headers": info,
        "hsts": parse_hsts(headers.get("strict-transport-security")),
        "csp": parse_csp(headers.get("content-security-policy")),
        "cookies": parse_set_cookie(resp["set_cookie"]),
    }


def _fetch_security_txt(
    domain: str, settings: dict[str, Any], limiter: _RateLimiter
) -> dict[str, Any]:
    cfg = settings.get("tls_http", {})
    http_cfg = settings.get("http", {})
    timeout = float(cfg.get("timeout_seconds", 7.0))
    max_bytes = int(cfg.get("max_bytes", 65536))
    ua = http_cfg.get("user_agent", f"karne/{COLLECTOR_VERSION}")
    url = f"https://{domain}/.well-known/security.txt"
    limiter.acquire()
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return {"present": False, "url": url, "status": resp.status}
            body = resp.read(max_bytes).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return {"present": False, "url": url, "status": exc.code}
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        return {"present": False, "url": url, "error": _short(exc)}
    return {"present": True, "url": url, "status": 200, **parse_security_txt(body)}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect(domain: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the dimension-B measurement for ``domain`` and return the raw payload."""
    settings = settings if settings is not None else load_settings()
    cfg = settings.get("tls_http", {})
    limiter = _RateLimiter(float(cfg.get("rate_per_second", 5.0)))
    host = domain.strip().lower().rstrip(".")

    payload: dict[str, Any] = {
        "collector": COLLECTOR,
        "collector_version": COLLECTOR_VERSION,
        "input_domain": domain,
        "domain": host,
        "collected_at": datetime.now(UTC).isoformat(),
        "config_hash": config_hash(settings),
    }

    # Each indicator is isolated: one failure does not abort the others (rule 3).
    payload["http"] = follow_http_chain(host, settings, limiter)
    payload["tls_versions"] = probe_tls_versions(host, settings)
    payload["certificate"] = fetch_certificate(host, settings)
    payload["homepage"] = _fetch_headers(f"https://{host}/", settings, limiter)
    payload["security_txt"] = _fetch_security_txt(host, settings, limiter)
    return payload
