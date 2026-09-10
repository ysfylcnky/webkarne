"""Karne command-line interface.

Sprint 0 exposes a single command, ``karne scan <domain>``, which runs the
DNS/email collector, optionally stores the raw result, and prints a factual
summary. Later sprints add ``batch``, ``rescore`` and ``export``.

The summary presents observed facts only; it assigns no scores or grades
(CLAUDE.md rule 1). Scoring is a separate layer introduced in Sprint 3.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from karne import __version__, storage
from karne.collectors import dns_email
from karne.models import STATUS_OK, STATUS_PARTIAL, DnsRecord, Scan, ScanResult

app = typer.Typer(
    add_completion=False,
    help="Karne - passive digital-hygiene measurement for domains.",
    no_args_is_help=True,
)

_INDICATORS = ("spf", "dmarc", "dkim", "mx", "mta_sts", "tls_rpt", "dnssec", "caa")


def _scan_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Partial if any indicator crashed (has an 'error' key); otherwise ok.

    Network failures (timeout/servfail/nxdomain) are normal measurement outcomes,
    not scan errors - the scan still completed.
    """
    errored = [
        name
        for name in _INDICATORS
        if isinstance(payload.get(name), dict) and "error" in payload[name]
    ]
    if not errored:
        return STATUS_OK, None
    detail = "; ".join(f"{name}: {payload[name]['error']}" for name in errored)
    return STATUS_PARTIAL, detail


def _store(db_path: Path, payload: dict[str, Any], status: str, error: str | None) -> int:
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        domain = storage.get_or_create_domain(conn, payload["domain"], source="manual")
        scan_id = storage.insert_scan(
            conn,
            Scan(
                domain_id=domain.id,
                scanner_version=__version__,
                config_hash=payload.get("config_hash"),
            ),
        )
        storage.insert_scan_result(
            conn,
            ScanResult(scan_id=scan_id, collector=dns_email.COLLECTOR_NAME, payload=payload),
        )
        storage.insert_dns_records(
            conn,
            [
                DnsRecord(scan_id=scan_id, **row)
                for row in dns_email.dns_records_from_payload(payload)
            ],
        )
        storage.finish_scan(conn, scan_id, status=status, error=error)
        return scan_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Summary formatting (factual presentation only)
# ---------------------------------------------------------------------------


def _spf_line(spf: dict[str, Any]) -> str:
    if "error" in spf:
        return f"error: {spf['error']}"
    if spf.get("multiple"):
        return f"MULTIPLE records ({len(spf['records'])}) - invalid configuration"
    if spf.get("present"):
        parsed = spf.get("parsed") or {}
        term = parsed.get("terminator")
        term_str = term["raw"] if term else "no 'all'"
        lk = spf.get("lookups") or {}
        total = lk.get("total_lookups", "?")
        limit = lk.get("limit", 10)
        line = f"present - terminator {term_str}, {total} lookups (limit {limit})"
        if lk.get("exceeds_limit"):
            line += " [exceeds RFC 7208 limit]"
        if lk.get("loop_detected"):
            line += " [include loop]"
        return line
    return f"not found (query status={spf.get('query', {}).get('status')})"


def _dmarc_line(dmarc: dict[str, Any]) -> str:
    if "error" in dmarc:
        return f"error: {dmarc['error']}"
    if dmarc.get("multiple"):
        return f"MULTIPLE records ({len(dmarc['records'])}) - invalid configuration"
    if dmarc.get("present"):
        p = dmarc.get("parsed") or {}
        parts = [f"p={p.get('p')}"]
        if p.get("sp"):
            parts.append(f"sp={p['sp']}")
        if p.get("pct"):
            parts.append(f"pct={p['pct']}")
        parts.append("rua=yes" if p.get("has_aggregate_reporting") else "rua=no")
        if not p.get("valid"):
            parts.append(f"invalid-syntax({','.join(p.get('issues', []))})")
        return "present - " + ", ".join(parts)
    return f"not found (query status={dmarc.get('query', {}).get('status')})"


def _dkim_line(dkim: dict[str, Any]) -> str:
    if "error" in dkim:
        return f"error: {dkim['error']}"
    tried = len(dkim.get("selectors_tried", []))
    found = dkim.get("found_selectors", [])
    if not found:
        return f"0/{tried} common selectors found (selector guessing)"
    details = []
    for attempt in dkim.get("attempts", []):
        if not attempt.get("present"):
            continue
        p = attempt.get("parsed", {})
        if p.get("p_empty"):
            details.append(f"{attempt['selector']} (revoked: empty p=)")
        else:
            details.append(f"{attempt['selector']} ({p.get('key_type')} {p.get('key_bits')} bit)")
    return f"{len(found)}/{tried} found: " + ", ".join(details)


def _mx_line(mx: dict[str, Any]) -> str:
    if "error" in mx:
        return f"error: {mx['error']}"
    if mx.get("present"):
        return f"{len(mx['records'])} record(s) - provider(s): {', '.join(mx.get('providers', []))}"
    return f"not found (query status={mx.get('query', {}).get('status')})"


def _mta_sts_line(mta: dict[str, Any]) -> str:
    if "error" in mta:
        return f"error: {mta['error']}"
    dns_part = mta.get("dns", {})
    if dns_part.get("present"):
        policy = mta.get("policy", {})
        mode = (policy.get("parsed") or {}).get("mode")
        suffix = f", policy={policy.get('status')}" + (f" mode={mode}" if mode else "")
        return "DNS record present" + suffix
    return f"not found (query status={dns_part.get('query', {}).get('status')})"


def _tls_rpt_line(tls: dict[str, Any]) -> str:
    if "error" in tls:
        return f"error: {tls['error']}"
    if tls.get("present"):
        return "present"
    return f"not found (query status={tls.get('query', {}).get('status')})"


def _caa_line(caa: dict[str, Any]) -> str:
    if "error" in caa:
        return f"error: {caa['error']}"
    if caa.get("present"):
        return f"{len(caa['records'])} record(s)"
    return f"not found (query status={caa.get('query', {}).get('status')})"


def _dnssec_line(dnssec: dict[str, Any]) -> str:
    if "error" in dnssec:
        return f"error: {dnssec['error']}"
    if dnssec.get("ds_present"):
        ad = dnssec.get("resolver_authenticated")
        ad_str = {True: "yes", False: "no", None: "unknown"}[ad]
        return f"DS present (resolver-validated: {ad_str})"
    return f"no DS record (query status={dnssec.get('query', {}).get('status')})"


def format_summary(
    payload: dict[str, Any], *, stored: bool, scan_id: int | None, status: str
) -> str:
    resolvers = ", ".join(payload.get("resolvers") or []) or "system default"
    lines = [
        f"Domain    : {payload['domain']}  (input: {payload['input_domain']})",
        f"Scanned   : {payload['collected_at']}",
        f"Resolvers : {resolvers}",
        "",
        f"  SPF      : {_spf_line(payload.get('spf', {}))}",
        f"  DMARC    : {_dmarc_line(payload.get('dmarc', {}))}",
        f"  DKIM     : {_dkim_line(payload.get('dkim', {}))}",
        f"  MX       : {_mx_line(payload.get('mx', {}))}",
        f"  MTA-STS  : {_mta_sts_line(payload.get('mta_sts', {}))}",
        f"  TLS-RPT  : {_tls_rpt_line(payload.get('tls_rpt', {}))}",
        f"  DNSSEC   : {_dnssec_line(payload.get('dnssec', {}))}",
        f"  CAA      : {_caa_line(payload.get('caa', {}))}",
        "",
    ]
    if stored:
        lines.append(f"Stored    : scan #{scan_id} (status={status})")
    else:
        lines.append("Stored    : no (--no-store)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.callback()
def _main() -> None:
    """Karne - passive digital-hygiene measurement for domains.

    A callback keeps ``scan`` as an explicit sub-command now, leaving room for
    ``batch`` / ``rescore`` / ``export`` in later sprints.
    """


@app.command()
def scan(
    domain: str = typer.Argument(..., help="Domain to scan, e.g. itu.edu.tr"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="Print the raw collector payload as JSON."
    ),
    no_store: bool = typer.Option(
        False, "--no-store", help="Measure only; do not write to the database."
    ),
    db: Path = typer.Option(
        storage.DEFAULT_DB_PATH, "--db", help="SQLite database path.", show_default=True
    ),
    settings_file: str = typer.Option(
        "", "--settings", help="Path to a settings.toml (defaults to config/settings.toml)."
    ),
) -> None:
    """Scan a domain's DNS/email hygiene (dimension A) and store the raw result."""
    settings = (
        dns_email.load_settings(settings_file) if settings_file else dns_email.load_settings()
    )
    payload = dns_email.collect(domain, settings)
    status, error = _scan_status(payload)

    scan_id: int | None = None
    if not no_store:
        scan_id = _store(db, payload, status, error)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        typer.echo(format_summary(payload, stored=not no_store, scan_id=scan_id, status=status))


if __name__ == "__main__":
    app()
