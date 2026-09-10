"""DNS / email collector — dimension A.

Single entry point: ``collect(domain) -> dict``. The output is RAW and
UNINTERPRETED (CLAUDE.md rule 1): it records what was observed, never a score or
a quality judgement. Every DNS query is logged with its result state, keeping
``nxdomain`` / ``noanswer`` / ``timeout`` / ``servfail`` / ``error`` distinct
(rule 6). A failure in one indicator does not abort the others (rule 3).

What is measured (PLAN.md section 3, dimension A): SPF (incl. the RFC 7208
10-lookup count over the include/redirect chain), DMARC, DKIM (common-selector
guessing), MX (with provider classification), MTA-STS (TXT + well-known policy),
TLS-RPT, DNSSEC (DS presence + resolver AD flag), and CAA.

Parsers in this module are pure functions of strings so they can be unit-tested
against fixtures with no network (see tests/). Network access is confined to the
injectable :class:`DnsClient` and the single MTA-STS HTTP GET.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import ssl
import threading
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dns.exception
import dns.flags
import dns.resolver

COLLECTOR_NAME = "dns_email"
COLLECTOR_VERSION = "0.1.0"

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.toml"

# SPF mechanisms that cause a DNS lookup and count against RFC 7208's limit of 10.
SPF_LOOKUP_MECHANISMS = frozenset({"include", "a", "mx", "ptr", "exists"})
SPF_LOOKUP_LIMIT = 10
# Guards against crafted/broken include loops while counting.
_SPF_MAX_DEPTH = 20
_SPF_MAX_STEPS = 100


# ===========================================================================
# Settings
# ===========================================================================


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> dict[str, Any]:
    """Load config/settings.toml. Raises if the file is missing or malformed."""
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def config_hash(settings: dict[str, Any]) -> str:
    """Stable hash of the effective settings, stored on each scan (K-03)."""
    blob = json.dumps(settings, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def normalize_domain(domain: str) -> str:
    """Lower-case, strip whitespace and a single trailing dot. No network."""
    return domain.strip().rstrip(".").lower()


# ===========================================================================
# DNS client (network) — injectable and fully logged
# ===========================================================================


@dataclass
class DnsQuery:
    """One DNS query and its outcome. ``status`` keeps failure modes distinct."""

    name: str
    rtype: str
    status: str  # ok / nxdomain / noanswer / timeout / servfail / error
    queried_at: str  # ISO-8601 UTC
    resolver: list[str]
    answers: list[str] = field(default_factory=list)
    rcode: str | None = None
    authenticated: bool | None = None  # DNSSEC AD flag (resolver's view; best-effort)
    error_detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class _RateLimiter:
    """Thread-safe minimum-interval gate: caps query *starts* to rate/second."""

    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second if rate_per_second and rate_per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self._interval
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def _extract_answers(rtype: str, answer: dns.resolver.Answer) -> list[str]:
    """Render each record as a faithful string (TXT joined, MX as 'pref host')."""
    out: list[str] = []
    for rdata in answer:
        if rtype == "TXT":
            out.append(b"".join(rdata.strings).decode("utf-8", "replace"))
        elif rtype == "MX":
            out.append(f"{rdata.preference} {rdata.exchange.to_text()}")
        else:
            out.append(rdata.to_text())
    return out


class DnsClient:
    """Resolver wrapper: per-query timeout, bounded retries, rate limit, full log."""

    def __init__(self, dns_settings: dict[str, Any]) -> None:
        self._resolver = dns.resolver.Resolver(configure=True)
        self._resolver.timeout = float(dns_settings.get("timeout_seconds", 5.0))
        self._resolver.lifetime = float(dns_settings.get("lifetime_seconds", 10.0))
        resolvers = dns_settings.get("resolvers") or []
        if resolvers:
            self._resolver.nameservers = list(resolvers)
        # Request DNSSEC records so the AD flag can be observed (best-effort).
        with contextlib.suppress(Exception):  # EDNS setup must not abort a scan
            self._resolver.use_edns(0, dns.flags.DO, 1232)
        self.nameservers = list(self._resolver.nameservers)
        self._retries = int(dns_settings.get("retries", 2))
        self._backoff = float(dns_settings.get("retry_backoff_seconds", 0.5))
        self._rate = _RateLimiter(float(dns_settings.get("rate_per_second", 10.0)))
        self._lock = threading.Lock()
        self.queries: list[DnsQuery] = []

    def _record(self, query: DnsQuery) -> DnsQuery:
        with self._lock:
            self.queries.append(query)
        return query

    def resolve(self, name: str, rtype: str) -> DnsQuery:
        """Resolve one name/type, never raising: failures become a logged status."""
        queried_at = datetime.now(UTC).isoformat()
        attempt = 0
        while True:
            self._rate.acquire()
            try:
                answer = self._resolver.resolve(name, rtype, raise_on_no_answer=True)
                ad = bool(answer.response.flags & dns.flags.AD)
                return self._record(
                    DnsQuery(
                        name,
                        rtype,
                        "ok",
                        queried_at,
                        self.nameservers,
                        answers=_extract_answers(rtype, answer),
                        rcode="NOERROR",
                        authenticated=ad,
                    )
                )
            except dns.resolver.NXDOMAIN:
                return self._record(
                    DnsQuery(
                        name, rtype, "nxdomain", queried_at, self.nameservers, rcode="NXDOMAIN"
                    )
                )
            except dns.resolver.NoAnswer:
                return self._record(
                    DnsQuery(name, rtype, "noanswer", queried_at, self.nameservers, rcode="NOERROR")
                )
            except dns.exception.Timeout as exc:
                attempt += 1
                if attempt <= self._retries:
                    time.sleep(self._backoff * attempt)
                    continue
                return self._record(
                    DnsQuery(
                        name,
                        rtype,
                        "timeout",
                        queried_at,
                        self.nameservers,
                        error_detail=str(exc),
                    )
                )
            except dns.resolver.NoNameservers as exc:
                detail = str(exc)
                status = "servfail" if "SERVFAIL" in detail.upper() else "error"
                return self._record(
                    DnsQuery(name, rtype, status, queried_at, self.nameservers, error_detail=detail)
                )
            except dns.exception.DNSException as exc:
                return self._record(
                    DnsQuery(
                        name, rtype, "error", queried_at, self.nameservers, error_detail=str(exc)
                    )
                )
            except Exception as exc:  # last resort: one query must never crash the scan
                return self._record(
                    DnsQuery(
                        name,
                        rtype,
                        "error",
                        queried_at,
                        self.nameservers,
                        error_detail=f"{type(exc).__name__}: {exc}",
                    )
                )


# ===========================================================================
# Pure parsers (no network) — the unit-tested core
# ===========================================================================

_SPF_QUALIFIERS = "+-~?"


def parse_spf_record(record: str) -> dict[str, Any]:
    """Parse one SPF record string into its mechanisms, terminator and modifiers.

    Pure and local: counts only the lookup-causing terms *in this record*
    (``lookup_terms_here``); the full chain count lives in
    :func:`count_spf_lookups`.
    """
    tokens = record.split()
    version_ok = bool(tokens) and tokens[0].lower() == "v=spf1"
    body_tokens = tokens[1:] if version_ok else tokens

    mechanisms: list[dict[str, Any]] = []
    includes: list[str] = []
    redirect: str | None = None
    exp: str | None = None
    unknown_modifiers: list[str] = []
    terminator: dict[str, Any] | None = None

    for tok in body_tokens:
        if "=" in tok and tok[0] not in _SPF_QUALIFIERS:
            name, _, val = tok.partition("=")
            nl = name.lower()
            if nl == "redirect":
                redirect = val
            elif nl == "exp":
                exp = val
            else:
                unknown_modifiers.append(tok)
            continue
        qualifier = tok[0] if tok and tok[0] in _SPF_QUALIFIERS else "+"
        body = tok[1:] if tok and tok[0] in _SPF_QUALIFIERS else tok
        mtype = body.split(":", 1)[0].split("/", 1)[0].lower()
        value = body.split(":", 1)[1] if ":" in body else None
        mech = {"qualifier": qualifier, "type": mtype, "value": value, "raw": tok}
        mechanisms.append(mech)
        if mtype == "all":
            terminator = mech  # last "all" wins
        elif mtype == "include" and value:
            includes.append(value)

    lookup_terms_here = sum(1 for m in mechanisms if m["type"] in SPF_LOOKUP_MECHANISMS)
    if redirect:
        lookup_terms_here += 1

    return {
        "version_ok": version_ok,
        "mechanisms": mechanisms,
        "terminator": terminator,
        "includes": includes,
        "redirect": redirect,
        "exp": exp,
        "unknown_modifiers": unknown_modifiers,
        "lookup_terms_here": lookup_terms_here,
    }


def count_spf_lookups(
    record: str,
    fetch_spf: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Count SPF DNS lookups over the include/redirect chain (RFC 7208 §4.6.4).

    ``fetch_spf(name)`` must return ``{"record": str | None, "status": str}`` for
    the SPF record at ``name``. Each include/a/mx/ptr/exists mechanism and the
    redirect modifier counts as one lookup; include and redirect targets are
    followed recursively.

    Method note (stored as ``method`` in the result): a/mx/ptr/exists are counted
    as one lookup each and their sub-lookups are NOT expanded. Raw records for the
    whole chain are kept in ``chain`` so a stricter count can be recomputed later.
    """
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    state = {"steps": 0, "loop_detected": False, "truncated": False}

    def walk(name: str, rec: str, depth: int) -> int:
        state["steps"] += 1
        if state["steps"] > _SPF_MAX_STEPS or depth > _SPF_MAX_DEPTH:
            state["truncated"] = True
            return 0
        parsed = parse_spf_record(rec)
        here = parsed["lookup_terms_here"]
        step = {
            "name": name,
            "record": rec,
            "lookup_terms_here": here,
            "includes": parsed["includes"],
            "redirect": parsed["redirect"],
        }
        chain.append(step)
        total = here
        targets = list(parsed["includes"])
        if parsed["redirect"]:
            targets.append(parsed["redirect"])
        for target in targets:
            if target in seen:
                state["loop_detected"] = True
                continue
            seen.add(target)
            fetched = fetch_spf(target)
            if fetched.get("record"):
                total += walk(target, fetched["record"], depth + 1)
            else:
                chain.append({"name": target, "record": None, "status": fetched.get("status")})
        return total

    total = walk("<root>", record, 0)
    return {
        "total_lookups": total,
        "exceeds_limit": total > SPF_LOOKUP_LIMIT,
        "limit": SPF_LOOKUP_LIMIT,
        "loop_detected": state["loop_detected"],
        "truncated": state["truncated"],
        "chain": chain,
        "method": "rfc7208_terms_recursive_simplified",
    }


_DMARC_P_VALUES = frozenset({"none", "quarantine", "reject"})


def parse_dmarc_record(record: str) -> dict[str, Any]:
    """Parse a DMARC record's tags and record syntactic validity (RFC 7489)."""
    parts = [p.strip() for p in record.split(";") if p.strip()]
    tags: dict[str, str] = {}
    order: list[str] = []
    for part in parts:
        key, sep, val = part.partition("=")
        if sep:
            k = key.strip().lower()
            tags[k] = val.strip()
            order.append(k)

    issues: list[str] = []
    if not order or order[0] != "v" or tags.get("v", "").lower() != "dmarc1":
        issues.append("missing_or_misplaced_version")
    if "p" not in tags:
        issues.append("missing_policy")
    elif tags["p"].lower() not in _DMARC_P_VALUES:
        issues.append("invalid_policy_value")
    if "pct" in tags:
        try:
            pct = int(tags["pct"])
            if not 0 <= pct <= 100:
                issues.append("pct_out_of_range")
        except ValueError:
            issues.append("pct_not_integer")

    return {
        "tags": tags,
        "p": tags.get("p"),
        "sp": tags.get("sp"),
        "pct": tags.get("pct"),
        "rua": tags.get("rua"),
        "ruf": tags.get("ruf"),
        "adkim": tags.get("adkim"),
        "aspf": tags.get("aspf"),
        "fo": tags.get("fo"),
        "has_aggregate_reporting": "rua" in tags,
        "valid": not issues,
        "issues": issues,
    }


def _der_read_tlv(data: bytes, i: int) -> tuple[int, bytes, int]:
    tag = data[i]
    i += 1
    length = data[i]
    i += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[i : i + n], "big")
        i += n
    value = data[i : i + length]
    return tag, value, i + length


def _der_integers(data: bytes) -> list[bytes]:
    """Collect every DER INTEGER value, descending into SEQUENCEs and BIT STRINGs."""
    ints: list[bytes] = []
    i = 0
    while i < len(data):
        try:
            tag, value, nxt = _der_read_tlv(data, i)
        except (IndexError, ValueError):
            break
        if tag == 0x02:  # INTEGER
            ints.append(value)
        elif tag == 0x03 and value:  # BIT STRING: skip the unused-bits byte, recurse
            ints.extend(_der_integers(value[1:]))
        elif tag & 0x20:  # constructed (e.g. SEQUENCE)
            ints.extend(_der_integers(value))
        if nxt <= i:
            break
        i = nxt
    return ints


def _rsa_key_bits(public_key_der: bytes) -> int | None:
    """RSA modulus size in bits from a DER SPKI or bare RSAPublicKey; None if unparsable."""
    ints = _der_integers(public_key_der)
    if not ints:
        return None
    modulus = max(ints, key=len).lstrip(b"\x00")
    if not modulus:
        return None
    return int.from_bytes(modulus, "big").bit_length()


def parse_dkim_record(record: str) -> dict[str, Any]:
    """Parse a DKIM key record: key type, key length (bits), and whether p= is empty."""
    tags: dict[str, str] = {}
    for part in record.split(";"):
        key, sep, val = part.partition("=")
        if sep:
            tags[key.strip().lower()] = val.strip()

    key_type = tags.get("k", "rsa").lower()
    p_value = tags.get("p")
    p_present = "p" in tags
    p_empty = p_present and p_value == ""

    key_bits: int | None = None
    if p_value:
        try:
            raw = base64.b64decode(p_value, validate=False)
            if key_type == "rsa":
                key_bits = _rsa_key_bits(raw)
            elif raw:
                # ed25519 and other raw-key types: report the raw key size in bits.
                key_bits = len(raw) * 8
        except Exception:  # noqa: BLE001 - malformed base64/DER must not crash parsing
            key_bits = None

    return {
        "tags": tags,
        "key_type": key_type,
        "key_bits": key_bits,
        "p_present": p_present,
        "p_empty": p_empty,  # empty p= signals a revoked key
        "testing": "y" in tags.get("t", "").split(":"),
    }


def classify_mx_provider(host: str, domain: str, mapping: dict[str, str]) -> str:
    """Classify an MX host: 'local' (inside the domain), a mapped provider, or 'other'."""
    h = host.rstrip(".").lower()
    d = domain.rstrip(".").lower()
    if h == d or h.endswith("." + d):
        return "local"
    best_label = "other"
    best_len = -1
    for suffix, label in mapping.items():
        s = suffix.rstrip(".").lower()
        if (h == s or h.endswith("." + s)) and len(s) > best_len:
            best_label, best_len = label, len(s)
    return best_label


def parse_mta_sts_policy(text: str) -> dict[str, Any]:
    """Parse an MTA-STS policy file (RFC 8461): version, mode, mx list, max_age."""
    mode: str | None = None
    version: str | None = None
    max_age: str | None = None
    mx: list[str] = []
    for line in text.splitlines():
        key, sep, val = line.partition(":")
        if not sep:
            continue
        k = key.strip().lower()
        v = val.strip()
        if k == "version":
            version = v
        elif k == "mode":
            mode = v
        elif k == "max_age":
            max_age = v
        elif k == "mx":
            mx.append(v)
    return {"version": version, "mode": mode, "mx": mx, "max_age": max_age}


# ===========================================================================
# Per-indicator collectors (network via the injected client)
# ===========================================================================


def _txt_matches(answers: list[str], prefix: str) -> list[str]:
    pref = prefix.lower()
    return [t for t in answers if t.strip().lower().startswith(pref)]


def collect_spf(domain: str, client: DnsClient) -> dict[str, Any]:
    query = client.resolve(domain, "TXT")
    records = _txt_matches(query.answers, "v=spf1")
    result: dict[str, Any] = {
        "query": query.as_dict(),
        "records": records,
        "present": bool(records),
        "multiple": len(records) > 1,  # multiple SPF records is itself an error state
    }
    if len(records) == 1:
        result["parsed"] = parse_spf_record(records[0])

        def fetch_spf(name: str) -> dict[str, Any]:
            q = client.resolve(name, "TXT")
            spf = _txt_matches(q.answers, "v=spf1")
            return {"record": spf[0] if len(spf) == 1 else None, "status": q.status}

        result["lookups"] = count_spf_lookups(records[0], fetch_spf)
    elif len(records) > 1:
        result["parsed"] = [parse_spf_record(r) for r in records]
    return result


def collect_dmarc(domain: str, client: DnsClient) -> dict[str, Any]:
    query = client.resolve(f"_dmarc.{domain}", "TXT")
    records = _txt_matches(query.answers, "v=dmarc1")
    result: dict[str, Any] = {
        "query": query.as_dict(),
        "records": records,
        "present": bool(records),
        "multiple": len(records) > 1,
    }
    if len(records) == 1:
        result["parsed"] = parse_dmarc_record(records[0])
    elif len(records) > 1:
        result["parsed"] = [parse_dmarc_record(r) for r in records]
    return result


def collect_dkim(domain: str, client: DnsClient, selectors: list[str]) -> dict[str, Any]:
    # DKIM selectors cannot be discovered from DNS; they are guessed. This is a
    # documented method limitation, flagged below as method=selector_guessing.
    def probe(selector: str) -> dict[str, Any]:
        query = client.resolve(f"{selector}._domainkey.{domain}", "TXT")
        dkim_txt = [
            t for t in query.answers if "p=" in t.lower() or t.strip().lower().startswith("v=dkim1")
        ]
        entry: dict[str, Any] = {
            "selector": selector,
            "query": query.as_dict(),
            "present": bool(dkim_txt),
        }
        if dkim_txt:
            entry["parsed"] = parse_dkim_record(dkim_txt[0])
        return entry

    workers = max(1, min(len(selectors), 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        attempts = list(pool.map(probe, selectors))

    return {
        "method": "selector_guessing",
        "selectors_tried": list(selectors),
        "attempts": attempts,
        "found_selectors": [a["selector"] for a in attempts if a["present"]],
    }


def collect_mx(domain: str, client: DnsClient, mx_map: dict[str, str]) -> dict[str, Any]:
    query = client.resolve(domain, "MX")
    records: list[dict[str, Any]] = []
    for ans in query.answers:
        pref_str, _, exchange = ans.partition(" ")
        try:
            preference = int(pref_str)
        except ValueError:
            preference = None
        records.append(
            {
                "preference": preference,
                "exchange": exchange,
                "provider": classify_mx_provider(exchange, domain, mx_map),
            }
        )
    records.sort(key=lambda r: (r["preference"] is None, r["preference"] or 0))
    return {
        "query": query.as_dict(),
        "present": bool(records),
        "records": records,
        "providers": sorted({r["provider"] for r in records}),
    }


def _http_get(url: str, http_settings: dict[str, Any]) -> dict[str, Any]:
    """Single short GET; redirects not followed (RFC 8461); all errors tolerated."""
    timeout = float(http_settings.get("timeout_seconds", 5.0))
    max_bytes = int(http_settings.get("max_bytes", 65536))
    user_agent = http_settings.get("user_agent", "karne/0.1")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: D401 - disable redirects
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent}, method="GET")
    result: dict[str, Any] = {"url": url, "redirected": False}
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            result["status"] = "ok"
            result["http_status"] = getattr(response, "status", None)
            result["truncated"] = len(body) > max_bytes
            result["body"] = body[:max_bytes].decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            result["status"] = "redirect_not_followed"
            result["redirected"] = True
        else:
            result["status"] = "http_error"
        result["http_status"] = exc.code
    except TimeoutError:
        result["status"] = "timeout"
    except (urllib.error.URLError, ssl.SSLError, OSError) as exc:
        result["status"] = "error"
        result["error_detail"] = f"{type(exc).__name__}: {exc}"
    return result


def collect_mta_sts(
    domain: str, client: DnsClient, http_settings: dict[str, Any]
) -> dict[str, Any]:
    query = client.resolve(f"_mta-sts.{domain}", "TXT")
    records = _txt_matches(query.answers, "v=stsv1")
    dns_part: dict[str, Any] = {
        "query": query.as_dict(),
        "records": records,
        "present": bool(records),
    }
    policy = _http_get(f"https://mta-sts.{domain}/.well-known/mta-sts.txt", http_settings)
    if policy.get("status") == "ok" and policy.get("body"):
        policy["parsed"] = parse_mta_sts_policy(policy["body"])
    return {"dns": dns_part, "policy": policy}


def collect_tls_rpt(domain: str, client: DnsClient) -> dict[str, Any]:
    query = client.resolve(f"_smtp._tls.{domain}", "TXT")
    records = _txt_matches(query.answers, "v=tlsrptv1")
    return {"query": query.as_dict(), "records": records, "present": bool(records)}


def collect_dnssec(domain: str, client: DnsClient) -> dict[str, Any]:
    query = client.resolve(domain, "DS")
    return {
        "query": query.as_dict(),
        "ds_present": query.status == "ok" and bool(query.answers),
        # AD reflects the resolver's validation, not our own verification.
        "resolver_authenticated": query.authenticated,
        "note": "resolver_authenticated is the resolver's DNSSEC AD flag, not local validation",
    }


def collect_caa(domain: str, client: DnsClient) -> dict[str, Any]:
    query = client.resolve(domain, "CAA")
    return {"query": query.as_dict(), "present": bool(query.answers), "records": query.answers}


# ===========================================================================
# Orchestration
# ===========================================================================


def _safe(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run one indicator; turn an unexpected crash into a recorded error (rule 3)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a broken indicator must not abort the scan
        return {"error": f"{type(exc).__name__}: {exc}"}


def collect(
    domain: str,
    settings: dict[str, Any] | None = None,
    client: DnsClient | None = None,
) -> dict[str, Any]:
    """Collect the raw DNS/email observations for ``domain``.

    Returns a single dict suitable for storage as ``scan_results.payload_json``.
    No scoring or judgement is applied (rule 1). ``settings`` defaults to
    ``config/settings.toml``; ``client`` is injectable for testing.
    """
    settings = settings if settings is not None else load_settings()
    normalized = normalize_domain(domain)
    client = client if client is not None else DnsClient(settings.get("dns", {}))

    dkim_selectors = settings.get("dkim", {}).get("selectors", [])
    mx_map = settings.get("mx_providers", {})
    http_settings = settings.get("http", {})

    payload: dict[str, Any] = {
        "collector": COLLECTOR_NAME,
        "collector_version": COLLECTOR_VERSION,
        "input_domain": domain,
        "domain": normalized,
        "collected_at": datetime.now(UTC).isoformat(),
        "resolvers": client.nameservers,
        "config_hash": config_hash(settings),
        "spf": _safe(lambda: collect_spf(normalized, client)),
        "dmarc": _safe(lambda: collect_dmarc(normalized, client)),
        "dkim": _safe(lambda: collect_dkim(normalized, client, dkim_selectors)),
        "mx": _safe(lambda: collect_mx(normalized, client, mx_map)),
        "mta_sts": _safe(lambda: collect_mta_sts(normalized, client, http_settings)),
        "tls_rpt": _safe(lambda: collect_tls_rpt(normalized, client)),
        "dnssec": _safe(lambda: collect_dnssec(normalized, client)),
        "caa": _safe(lambda: collect_caa(normalized, client)),
    }
    payload["queries"] = [q.as_dict() for q in client.queries]
    return payload


def dns_records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a collect() payload into dns_records rows (rtype/selector/value/valid/notes).

    A convenience projection over the authoritative raw payload. Every indicator
    yields at least one row so the query state (incl. "could not measure") is
    queryable; ``valid`` carries only syntactic-validity observations, never a score.
    Each row is a dict ready to splat into ``models.DnsRecord`` with a scan_id.
    """
    rows: list[dict[str, Any]] = []

    def add(rtype, value=None, selector=None, valid=None, notes=None):
        rows.append(
            {"rtype": rtype, "value": value, "selector": selector, "valid": valid, "notes": notes}
        )

    def status_of(section: dict[str, Any]) -> str | None:
        return section.get("query", {}).get("status")

    spf = payload.get("spf", {})
    if "error" in spf:
        add("SPF", notes=f"error={spf['error']}")
    elif spf.get("records"):
        parsed = spf.get("parsed")
        if isinstance(parsed, list):
            for rec, p in zip(spf["records"], parsed, strict=False):
                add("SPF", value=rec, valid=p.get("version_ok"), notes="multiple_records")
        else:
            lk = spf.get("lookups") or {}
            note = (
                f"lookups={lk['total_lookups']};exceeds_limit={lk['exceeds_limit']}" if lk else None
            )
            add("SPF", value=spf["records"][0], valid=(parsed or {}).get("version_ok"), notes=note)
    else:
        add("SPF", notes=f"status={status_of(spf)}")

    dmarc = payload.get("dmarc", {})
    if "error" in dmarc:
        add("DMARC", notes=f"error={dmarc['error']}")
    elif dmarc.get("records"):
        parsed = dmarc.get("parsed")
        if isinstance(parsed, list):
            for rec, p in zip(dmarc["records"], parsed, strict=False):
                add("DMARC", value=rec, valid=p.get("valid"), notes="multiple_records")
        else:
            p = parsed or {}
            add("DMARC", value=dmarc["records"][0], valid=p.get("valid"), notes=f"p={p.get('p')}")
    else:
        add("DMARC", notes=f"status={status_of(dmarc)}")

    dkim = payload.get("dkim", {})
    if "error" in dkim:
        add("DKIM", notes=f"error={dkim['error']}")
    else:
        for attempt in dkim.get("attempts", []):
            if not attempt.get("present"):
                continue
            p = attempt.get("parsed", {})
            answers = attempt.get("query", {}).get("answers", [])
            add(
                "DKIM",
                selector=attempt["selector"],
                value=answers[0] if answers else None,
                notes=f"key_type={p.get('key_type')};key_bits={p.get('key_bits')};"
                f"p_empty={p.get('p_empty')}",
            )
        if not dkim.get("found_selectors"):
            add("DKIM", notes="status=none_found;method=selector_guessing")

    mx = payload.get("mx", {})
    if "error" in mx:
        add("MX", notes=f"error={mx['error']}")
    elif mx.get("records"):
        for rec in mx["records"]:
            add(
                "MX",
                value=f"{rec['preference']} {rec['exchange']}",
                notes=f"provider={rec['provider']}",
            )
    else:
        add("MX", notes=f"status={status_of(mx)}")

    mta = payload.get("mta_sts", {})
    if "error" in mta:
        add("MTA-STS", notes=f"error={mta['error']}")
    else:
        dns_part = mta.get("dns", {})
        policy = mta.get("policy", {})
        if dns_part.get("records"):
            mode = (policy.get("parsed") or {}).get("mode")
            add(
                "MTA-STS",
                value=dns_part["records"][0],
                notes=f"policy_status={policy.get('status')};mode={mode}",
            )
        else:
            add("MTA-STS", notes=f"status={status_of(dns_part)}")

    tls = payload.get("tls_rpt", {})
    if "error" in tls:
        add("TLS-RPT", notes=f"error={tls['error']}")
    elif tls.get("records"):
        add("TLS-RPT", value=tls["records"][0])
    else:
        add("TLS-RPT", notes=f"status={status_of(tls)}")

    dnssec = payload.get("dnssec", {})
    if "error" in dnssec:
        add("DS", notes=f"error={dnssec['error']}")
    else:
        add(
            "DS",
            value="present" if dnssec.get("ds_present") else "absent",
            valid=dnssec.get("resolver_authenticated"),
            notes=f"status={status_of(dnssec)}",
        )

    caa = payload.get("caa", {})
    if "error" in caa:
        add("CAA", notes=f"error={caa['error']}")
    elif caa.get("records"):
        for rec in caa["records"]:
            add("CAA", value=rec)
    else:
        add("CAA", notes=f"status={status_of(caa)}")

    return rows
