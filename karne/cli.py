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
from karne.analyze import rescore, scoring
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


def _tls_http_summary(payload: dict[str, Any]) -> str:
    """Compact, factual summary of a dimension-B (TLS/HTTP) payload (ASCII-only)."""
    http = payload.get("http", {})
    tv = payload.get("tls_versions", {})
    cert = payload.get("certificate", {})
    hp = payload.get("homepage", {})
    hsts = hp.get("hsts", {}) if hp else {}
    if cert.get("verified"):
        cert_line = f"verified, {cert.get('issuer')}, {cert.get('days_remaining')} days left"
    elif cert.get("verified") is False:
        cert_line = f"NOT verified ({cert.get('verify_error')})"
    else:
        cert_line = f"not obtained ({cert.get('error')})"
    if hsts.get("present"):
        hsts_line = f"max-age={hsts.get('max_age')}"
        if hsts.get("include_subdomains"):
            hsts_line += " +includeSubDomains"
        if hsts.get("preload"):
            hsts_line += " +preload"
    else:
        hsts_line = "absent"
    headers = ", ".join((hp.get("security_headers") or {}).keys()) if hp else ""
    return "\n".join(
        [
            "  [transport - TLS/HTTP]",
            f"  HTTPS    : reached_https={http.get('reached_https')} hops={http.get('hops')}"
            f" cleartext_after_https={http.get('cleartext_after_https')}",
            f"  TLS      : supported={', '.join(tv.get('supported', [])) or 'none'}",
            f"  Cert     : {cert_line}",
            f"  HSTS     : {hsts_line}",
            f"  Headers  : {headers or 'none'}",
            f"  sec.txt  : {'present' if payload.get('security_txt', {}).get('present') else 'no'}",
        ]
    )


def _web_privacy_summary(payload: dict[str, Any]) -> str:
    """Compact, factual summary of a dimension-C (browser) payload (ASCII-only).

    Counts only: no tracker labels, no first/third-party split (that is analysis).
    """
    browser = payload.get("browser") or {}
    lines = [
        "  [privacy - browser]",
        f"  Browser  : chromium {browser.get('browser_version')}"
        f" (playwright {browser.get('playwright_version')}, headless={browser.get('headless')})",
    ]
    for name, state in (payload.get("states") or {}).items():
        outcome = state.get("outcome")
        if outcome == "not_run":
            lines.append(f"  {name:9}: not run ({state.get('reason')})")
            continue
        page = state.get("page") or {}
        storage = state.get("storage") or {}
        hosts = {r.get("host") for r in state.get("requests") or [] if r.get("host")}
        line = f"  {name:9}: {outcome}"
        if state.get("error"):
            line += f" ({state['error'].get('message')})"
        if state.get("blocked_evidence"):
            line += f" evidence={', '.join(state['blocked_evidence'])}"
        lines.append(line)
        lines.append(
            f"             final={page.get('final_url')} status={page.get('main_status')}"
            f" load_ms={page.get('load_ms')}"
        )
        http_only = sum(1 for c in state.get("cookies") or [] if c.get("http_only"))
        lines.append(
            f"             cookies={len(state.get('cookies') or [])} (httpOnly={http_only})"
            f" localStorage={len(storage.get('local_storage_keys') or [])}"
            f" sessionStorage={len(storage.get('session_storage_keys') or [])}"
        )
        truncated = " [truncated]" if state.get("requests_truncated") else ""
        lines.append(
            f"             requests={state.get('request_count')}{truncated}"
            f" distinct_hosts={len(hosts)}"
        )
        lines.extend(_consent_lines(state))
    return "\n".join(lines)


def _consent_lines(state: dict[str, Any]) -> list[str]:
    """Consent-UI observation and, for the rejected state, what the click did."""
    out: list[str] = []
    ui = state.get("consent_ui")
    if ui:
        banner = ui.get("banner") or {}
        cmps = ",".join(c["id"] for c in ui.get("cmp") or []) or "none"
        if banner.get("found"):
            visible = [c for c in ui.get("controls") or [] if c.get("visible")]
            roles = ",".join(sorted({c["matched_role"] for c in visible if c.get("matched_role")}))
            where = " shadow" if banner.get("in_shadow_dom") else ""
            banner_str = f"{banner.get('rule')}{where} visible_roles={roles or '-'}"
        else:
            banner_str = "not found"
        out.append(f"             consent_ui: cmp={cmps} banner={banner_str}")
    action = state.get("consent_action")
    if action:
        control = action.get("control") or {}
        label = f" '{control.get('text')}' ({control.get('rule')})" if control else ""
        reload = state.get("reload") or {}
        reload_str = f" reload={reload.get('status')}" if reload.get("performed") else ""
        phases: dict[str, int] = {}
        for r in state.get("requests") or []:
            phases[r.get("phase") or "-"] = phases.get(r.get("phase") or "-", 0) + 1
        by_phase = " ".join(f"{k}={v}" for k, v in phases.items())
        out.append(f"             reject: {action.get('result')}{label}{reload_str}")
        out.append(f"             requests by phase: {by_phase}")
    return out


def format_summary(
    payload: dict[str, Any],
    *,
    stored: bool,
    scan_id: int | None,
    status: str,
    show_stored: bool = True,
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
    if show_stored:
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
    collectors: str = typer.Option(
        ",".join(batch.DEFAULT_COLLECTORS),
        "--collectors",
        help=(
            "Comma-separated dimensions to run: email, transport (default: both), "
            "privacy (real browser; needs `uv sync --group privacy`)."
        ),
    ),
    db: Path = typer.Option(
        storage.DEFAULT_DB_PATH, "--db", help="SQLite database path.", show_default=True
    ),
    settings_file: str = typer.Option(
        "", "--settings", help="Path to a settings.toml (defaults to config/settings.toml)."
    ),
) -> None:
    """Scan a domain (A email, B transport, and/or C privacy) and store the raw results."""
    settings = (
        dns_email.load_settings(settings_file) if settings_file else dns_email.load_settings()
    )
    names = [c.strip() for c in collectors.split(",") if c.strip()]
    try:
        specs = batch.resolve_specs(names)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    outcomes = batch.collect_bundle(domain, settings, specs)
    by_dim = {o.spec.dimension: o for o in outcomes}

    scan_id: int | None = None
    status = batch.combine_status(outcomes)[0]
    if not no_store:
        conn = storage.connect(db)
        try:
            storage.init_db(conn)
            scan_id, status, _ = batch.store_bundle(conn, domain, outcomes)
        finally:
            conn.close()

    if json_output:
        payloads = {o.spec.collector: o.payload for o in outcomes if o.payload is not None}
        typer.echo(json.dumps(payloads, indent=2, ensure_ascii=False))
        return

    blocks: list[str] = []
    if "email" in by_dim and by_dim["email"].payload is not None:
        blocks.append(
            format_summary(
                by_dim["email"].payload,
                stored=False,
                scan_id=scan_id,
                status=status,
                show_stored=False,
            )
        )
    if "transport" in by_dim and by_dim["transport"].payload is not None:
        blocks.append(_tls_http_summary(by_dim["transport"].payload))
    if "privacy" in by_dim and by_dim["privacy"].payload is not None:
        blocks.append(_web_privacy_summary(by_dim["privacy"].payload))
    for o in outcomes:
        if o.payload is None:
            blocks.append(f"  [{o.spec.dimension}] collector error: {o.error}")
    if not no_store:
        blocks.append(f"Stored    : scan #{scan_id} (status={status})")
    else:
        blocks.append("Stored    : no (--no-store)")
    typer.echo("\n\n".join(blocks))


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
    collectors: str = typer.Option(
        ",".join(batch.DEFAULT_COLLECTORS),
        "--collectors",
        help="Comma-separated dimensions to run: email, transport (default: both).",
    ),
) -> None:
    """Scan the frame (dimensions A email and/or B transport) in parallel, resumably.

    Applies the selected collectors to every pending domain in the ``domains`` table,
    storing one ``scan_results`` row per collector. Re-running the same ``--run-label``
    resumes: already-completed domains (ok/partial) are skipped — so adding a collector
    to an existing round needs a NEW round label. Never scores or judges (rule 1); it
    only stores raw measurements, exactly like ``karne scan``.
    """
    collector_names = [c.strip() for c in collectors.split(",") if c.strip()]
    try:
        batch.resolve_batch_specs(collector_names)  # validate before touching the DB
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
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
            collectors=collector_names,
        )
        typer.echo("")
        typer.echo(progress.summary())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# rescore command (Sprint 3) — derive scores/findings from stored raw data
# ---------------------------------------------------------------------------


@app.command("rescore")
def rescore_cmd(
    scan_id: int = typer.Option(0, "--scan-id", help="Rescore only this scan id (0 = not by id)."),
    run_label: str = typer.Option(
        "", "--run-label", help="Rescore every scan in this round (e.g. 2026-09)."
    ),
    only_unscored: bool = typer.Option(
        False,
        "--only-unscored",
        help="Only scans with no score yet for the dimension (incremental).",
    ),
    dimension: str = typer.Option(
        "email", "--dimension", help="Scoring dimension: 'email' (A) or 'transport' (B)."
    ),
    scoring_file: str = typer.Option(
        "", "--scoring", help="Path to a scoring.toml (defaults to config/scoring.toml)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show how many scans would be (re)scored and exit."
    ),
    db: Path = typer.Option(
        storage.DEFAULT_DB_PATH, "--db", help="SQLite database path.", show_default=True
    ),
) -> None:
    """Derive scores/findings from stored raw data, using a versioned ruleset (K-02/K-03).

    Reads ``scan_results`` and writes the derived ``scores``/``findings``; it NEVER
    modifies raw data (rule 5). Scores/findings are reproducible, so re-running is
    safe: a scan's prior derived rows for the dimension are replaced, and each
    ``scores`` row records its ``ruleset_version`` (so November's raw data can be
    re-graded with May's rules). Target one ``--scan-id``, one ``--run-label``, or
    (default) all not-yet-scored scans.
    """
    if dimension not in rescore.SUPPORTED_DIMENSIONS:
        typer.echo(
            f"Unknown dimension '{dimension}'. Supported: "
            f"{', '.join(sorted(rescore.SUPPORTED_DIMENSIONS))}.",
            err=True,
        )
        raise typer.Exit(code=2)

    ruleset = scoring.load_ruleset(scoring_file or None)
    version = ruleset.get("version")
    sid = scan_id or None
    label = run_label or None

    conn = storage.connect(db)
    try:
        storage.init_db(conn)
        if sid is not None:
            ids = [sid]
        else:
            ids = storage.select_scans_for_scoring(
                conn,
                run_label=label,
                only_unscored=only_unscored,
                dimension=dimension,
                collector=rescore.collector_for(dimension),
            )

        selectors = []
        if sid is not None:
            selectors.append(f"scan-id={sid}")
        if label is not None:
            selectors.append(f"run-label={label}")
        if only_unscored:
            selectors.append("only-unscored")
        scope = (" [" + ", ".join(selectors) + "]") if selectors else " [all scored+unscored]"
        typer.echo(
            f"Rescore dimension '{dimension}' with ruleset {version}: "
            f"{len(ids)} scan(s) selected{scope}."
        )

        if dry_run:
            typer.echo("Dry run: nothing written.")
            return
        if not ids:
            typer.echo("Nothing to rescore.")
            return

        every = max(1, min(500, len(ids) // 20))

        def _report(i: int, n: int) -> None:
            if i % every == 0 or i == n:
                typer.echo(f"  [{i}/{n}] rescored", err=True)

        summary = rescore.rescore_scans(conn, ids, ruleset, dimension=dimension, progress=_report)
        typer.echo("")
        typer.echo(summary.summary_line())
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
