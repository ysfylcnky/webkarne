"""Karne command-line interface.

Sprint 0 exposes a single command, ``karne scan <domain>``, which runs the
DNS/email collector, optionally stores the raw result, and prints a factual
summary. Later sprints add ``batch``, ``rescore`` and ``export``.

The summary presents observed facts only; it assigns no scores or grades
(CLAUDE.md rule 1). Scoring is a separate layer introduced in Sprint 3.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from karne import batch, frontier, storage
from karne.collectors import dns_email
from karne.models import Domain

app = typer.Typer(
    add_completion=False,
    help="Karne - passive digital-hygiene measurement for domains.",
    no_args_is_help=True,
)


def _scan_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Delegate to the shared status logic (kept as a thin CLI-local alias)."""
    return batch.scan_status(payload)


def _store(db_path: Path, payload: dict[str, Any], status: str, error: str | None) -> int:
    """Persist a single ad-hoc scan (no run_label) via the shared write contract."""
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        return batch.store_scan(conn, payload, status=status, error=error, run_label=None)
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


def _dane_line(dane: dict[str, Any]) -> str:
    if "error" in dane:
        return f"error: {dane['error']}"
    hosts = dane.get("hosts", [])
    if not hosts:
        return "not checked (no MX hosts)"
    present = [h["mx_host"] for h in hosts if h.get("present")]
    if present:
        return f"{len(present)}/{len(hosts)} MX host(s) with TLSA: {', '.join(present)}"
    return f"0/{len(hosts)} MX host(s) with TLSA records"


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
        f"  DANE     : {_dane_line(payload.get('dane', {}))}",
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


# ---------------------------------------------------------------------------
# batch command (Sprint 2) — scan the whole frame, resumable, rate-limited
# ---------------------------------------------------------------------------


@app.command("batch")
def batch_scan(
    run_label: str = typer.Option(
        "", "--run-label", help="Round label (default: current UTC month, e.g. 2026-11)."
    ),
    sector: str = typer.Option(
        "", "--sector", help="Only scan domains in this sector (e.g. bank, university)."
    ),
    limit: int = typer.Option(
        0, "--limit", help="Scan at most N pending domains (0 = no cap). Good for validation runs."
    ),
    concurrency: int = typer.Option(
        0, "--concurrency", help="Override [dns].concurrency parallel domain scans (0 = config)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show the plan (done / pending / status breakdown) and exit."
    ),
    db: Path = typer.Option(
        storage.DEFAULT_DB_PATH, "--db", help="SQLite database path.", show_default=True
    ),
    settings_file: str = typer.Option(
        "", "--settings", help="Path to a settings.toml (defaults to config/settings.toml)."
    ),
) -> None:
    """Scan the frame (dimension A) in parallel, resumably, into a monthly round.

    Applies the existing dns_email collector to every pending domain in the
    ``domains`` table. Re-running the same ``--run-label`` resumes: already-completed
    domains (ok/partial) are skipped. This never scores or judges (rule 1); it only
    stores raw measurements, exactly like ``karne scan``.
    """
    settings = (
        dns_email.load_settings(settings_file) if settings_file else dns_email.load_settings()
    )
    label = run_label or batch.default_run_label()
    sector_filter = sector or None
    limit_val = limit or None
    conc = concurrency or None

    conn = storage.connect(db)
    try:
        storage.init_db(conn)
        pending = storage.select_domains_to_scan(conn, label, sector=sector_filter, limit=limit_val)
        scope_total = storage.count_domains(conn, sector=sector_filter)
        already = storage.count_done_domains(conn, label, sector=sector_filter)
        typer.echo(
            f"Round '{label}': {scope_total} domains in scope"
            + (f" (sector={sector_filter})" if sector_filter else "")
            + f", {already} already done, {len(pending)} to scan this pass."
        )

        if dry_run:
            counts = storage.run_status_counts(conn, label, sector=sector_filter)
            if counts:
                breakdown = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                typer.echo(f"Scans so far this round (by status): {breakdown}")
            typer.echo("Dry run: nothing scanned.")
            return

        if not pending:
            typer.echo("Nothing to scan. (Round already complete for this scope.)")
            return

        def _report(p: batch.BatchProgress) -> None:
            typer.echo("  " + p.progress_line(), err=True)  # stderr: unbuffered, live

        # Show progress often on small validation runs, sparsely on a full run.
        every = max(1, min(50, len(pending) // 20))

        progress = batch.run_batch(
            conn,
            settings,
            run_label=label,
            sector=sector_filter,
            limit=limit_val,
            concurrency=conc,
            progress_cb=_report,
            progress_every=every,
        )
        typer.echo("")
        typer.echo(progress.summary())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# frontier command (Sprint 1) — build the Türkiye sample frame (list only)
# ---------------------------------------------------------------------------


def _frame_entry_to_domain(entry: frontier.FrameEntry) -> Domain:
    return Domain(
        domain=entry.domain,
        source=entry.source,
        sector=entry.sector,
        is_public_body=entry.is_public_body,
    )


def _write_manifest(manifest: dict, out_dir: Path, list_id: str | None) -> Path:
    """Write the frame manifest as timestamped JSON (never overwrites a prior run)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"frame_{list_id or 'local'}_{stamp}.json"
    path = out_dir / name
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


@app.command("frontier")
def frontier_build(  # noqa: PLR0913 (a few independent, optional knobs)
    list_id: str = typer.Option(
        "", "--list-id", help="Tranco permanent list id (tranco-list.eu/list/<ID>)."
    ),
    tranco_file: str = typer.Option(
        "", "--tranco-file", help="Use an already-downloaded Tranco CSV instead of fetching."
    ),
    top: int = typer.Option(
        0, "--top", help="Download only the top N ranks (0 = full); ignored with --tranco-file."
    ),
    no_curated: bool = typer.Option(
        False, "--no-curated", help="Exclude the curated Turkish generic-TLD (.com) set."
    ),
    no_store: bool = typer.Option(
        False, "--no-store", help="Build and report only; do not write the domains table."
    ),
    db: Path = typer.Option(
        storage.DEFAULT_DB_PATH, "--db", help="SQLite database path.", show_default=True
    ),
    manifest_dir: Path = typer.Option(
        Path("data/frontier"), "--manifest-dir", help="Where to write the run manifest JSON."
    ),
) -> None:
    """Build the Türkiye sample frame and write it to the domains table (list only).

    This produces a domain LIST; it does not scan any domain (that is Sprint 2). A
    source is required: either an already-downloaded ``--tranco-file`` or a
    ``--list-id`` to fetch. The permanent list id is recorded in the run manifest
    for reproducibility.
    """
    if not tranco_file and not list_id:
        raise typer.BadParameter("provide --tranco-file or --list-id")

    if tranco_file:
        source_path = Path(tranco_file)
        source_url = None
        if not source_path.exists():
            raise typer.BadParameter(f"tranco file not found: {source_path}")
    else:
        source_url = frontier.tranco_download_url(list_id, top=top or None)
        settings = dns_email.load_settings()
        ua = settings.get("http", {}).get("user_agent", "karne-frontier/0.1")
        dest = Path("data/tranco") / f"tranco_{list_id}{f'_top{top}' if top else '_full'}.csv"
        typer.echo(f"Downloading Tranco list {list_id} -> {dest} ...")
        source_path = frontier.fetch_tranco_csv(list_id, dest, top=top or None, user_agent=ua)

    rows = frontier.read_tranco_csv(source_path)
    entries = frontier.build_frame(rows, include_curated=not no_curated)
    curated_note = "curated_tr_com" if not no_curated else "no curated set"
    manifest = frontier.frame_manifest(
        entries,
        tranco_list_id=list_id or None,
        tranco_source_url=source_url,
        cctld_source=f"Tranco .tr subset + {curated_note}",
    )

    store_result: dict[str, int] | None = None
    if not no_store:
        conn = storage.connect(db)
        try:
            storage.init_db(conn)
            store_result = storage.add_domains(conn, [_frame_entry_to_domain(e) for e in entries])
        finally:
            conn.close()

    manifest_path = _write_manifest(manifest, manifest_dir, list_id or None)
    typer.echo(_format_frontier_summary(manifest, store_result, manifest_path, source_path))


def _format_frontier_summary(
    manifest: dict, store: dict | None, manifest_path: Path, source_path: Path
) -> str:
    lines = [
        f"Frame     : {manifest['total_domains']} domains "
        f"(frontier {manifest['frontier_version']})",
        f"Source    : {source_path}  (list id: {manifest['tranco_list_id'] or '-'})",
        "",
        "  Sectors:",
    ]
    for sector, n in sorted(manifest["sector_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"    {sector:14}: {n}")
    lines.append(f"  is_public_body : {manifest['is_public_body_count']}")
    lines.append("")
    lines.append("  By source:")
    for src, n in sorted(manifest["source_counts"].items()):
        lines.append(f"    {src:16}: {n}")
    lines.append("  By method:")
    for method, n in sorted(manifest["method_counts"].items()):
        lines.append(f"    {method:16}: {n}")
    lines.append("")
    if store is not None:
        lines.append(f"Stored    : {store['added']} added, {store['updated']} updated")
    else:
        lines.append("Stored    : no (--no-store)")
    lines.append(f"Manifest  : {manifest_path}")
    return "\n".join(lines)


if __name__ == "__main__":
    app()
