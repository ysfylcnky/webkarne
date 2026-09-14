"""Read-only report data layer for the web UI.

Reads a frozen scan (scores + findings) from the SQLite store and shapes it for
the templates. It only ever READS — raw scan data is never modified (rule 5) and
scoring is never done here (K-02/K-03); grades/findings come straight from the
`scores`/`findings` tables the scoring layer produced.

The composite/overall grade is deliberately absent: no composite rule exists in
config/scoring.toml yet, and only the email + transport dimensions are collected,
so the Overview shows a partial-measurement state instead of an invented number.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "karne.db"

# Display order of the four dimensions (PLAN § 3).
DIMENSION_ORDER = ("email", "transport", "privacy", "tech")
DIMENSION_NUM = {"email": "01", "transport": "02", "privacy": "03", "tech": "04"}
DIMENSION_COLLECTOR = {"email": "dns_email", "transport": "tls_http"}
DIMENSION_PREFIX = {"email": "EMAIL_", "transport": "TRANSPORT_"}

# Severity ranking for ordering findings (high first) and for "featured" picks.
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}

# Grade buckets for the sector distribution histogram, best → worst.
GRADE_ORDER = ("A", "B", "C", "D", "F")

# Sectors that carry a real, labelled cohort in the frame; anything else
# ("unknown"/NULL) has no meaningful peer group to compare against (§ 4.5).
LABELLED_SECTORS = frozenset(
    {"bank", "university", "public_body", "municipality", "hospital", "ecommerce", "media"}
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def latest_scan_id(domain: str) -> int | None:
    """Most recent scan id for a domain, or None if the domain has no scan."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT s.id
            FROM scans s JOIN domains d ON d.id = s.domain_id
            WHERE d.domain = ?
            ORDER BY s.started_at DESC
            LIMIT 1
            """,
            (domain,),
        ).fetchone()
    return row["id"] if row else None


def load_report(scan_id: int) -> dict | None:
    """Shape one scan's stored scores and findings for the templates.

    Returns None if the scan does not exist. Dimensions carry ``measured`` so the
    UI can show the three states (§ 8.2): scored, not-in-this-scan, unmeasured.
    """
    with _connect() as conn:
        scan = conn.execute(
            """
            SELECT s.id, s.started_at, s.status, s.error, s.run_label, d.domain
            FROM scans s JOIN domains d ON d.id = s.domain_id
            WHERE s.id = ?
            """,
            (scan_id,),
        ).fetchone()
        if scan is None:
            return None

        scores = {
            r["dimension"]: r
            for r in conn.execute(
                "SELECT dimension, raw_score, grade, ruleset_version FROM scores WHERE scan_id = ?",
                (scan_id,),
            )
        }
        findings = [
            dict(r)
            for r in conn.execute(
                "SELECT code, severity, evidence_json, fix_hint_key "
                "FROM findings WHERE scan_id = ?",
                (scan_id,),
            )
        ]

    findings.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 9), f["code"]))

    dimensions = []
    for dim in DIMENSION_ORDER:
        row = scores.get(dim)
        dimensions.append(
            {
                "key": dim,
                "num": DIMENSION_NUM[dim],
                "measured": row is not None,
                "grade": row["grade"] if row else None,
                "score": _fmt_score(row["raw_score"]) if row else None,
                "ruleset": row["ruleset_version"] if row else None,
            }
        )

    measured = [d for d in dimensions if d["measured"]]
    return {
        "scan_id": scan["id"],
        "domain": scan["domain"],
        "date_iso": scan["started_at"],
        "status": scan["status"],
        "run_label": scan["run_label"],
        "dimensions": dimensions,
        "measured_count": len(measured),
        "total_dimensions": len(DIMENSION_ORDER),
        "findings": findings,
        "featured_findings": findings[:3],
        "finding_count": len(findings),
    }


def _fmt_score(raw: float | None) -> str | None:
    """Trim a trailing ``.0`` so 55.5 stays 55.5 but 65.0 shows as 65.

    An insufficient-data grade ("I") carries no numeric score; return None so the
    grade renders letter-only instead of crashing the page.
    """
    if raw is None:
        return None
    return f"{raw:.1f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------- dimension view


def dimension_detail(scan_id: int, dim: str) -> dict | None:
    """Per-control detail for one dimension of one scan.

    Control states are derived from the RAW collector payload (present / absent /
    could-not-measure / not-applicable) and overlaid with the findings that the
    scoring layer produced. The web layer does not re-score — it only presents the
    three measurement states honestly (§ 8.2). Returns None if the scan is absent.
    """
    with _connect() as conn:
        scan = conn.execute(
            """
            SELECT s.id, s.started_at, d.domain
            FROM scans s JOIN domains d ON d.id = s.domain_id
            WHERE s.id = ?
            """,
            (scan_id,),
        ).fetchone()
        if scan is None:
            return None
        score = conn.execute(
            "SELECT raw_score, grade, ruleset_version FROM scores "
            "WHERE scan_id = ? AND dimension = ?",
            (scan_id, dim),
        ).fetchone()
        findings = [
            dict(r)
            for r in conn.execute(
                "SELECT code, severity, evidence_json, fix_hint_key "
                "FROM findings WHERE scan_id = ?",
                (scan_id,),
            )
        ]
        collector = DIMENSION_COLLECTOR.get(dim)
        payload = {}
        if collector is not None:
            prow = conn.execute(
                "SELECT payload_json FROM scan_results WHERE scan_id = ? AND collector = ?",
                (scan_id, collector),
            ).fetchone()
            if prow is not None:
                payload = json.loads(prow["payload_json"])

    base = {
        "scan_id": scan["id"],
        "domain": scan["domain"],
        "date_iso": scan["started_at"],
        "dim": dim,
    }

    # No collector (privacy/tech) or no score → not measured in this scan.
    if collector is None or score is None:
        return {
            **base,
            "measured": False,
            "grade": None,
            "score": None,
            "controls": [],
            "finding_count": 0,
            "severity_counts": {},
            "findings": [],
        }

    dim_findings = [f for f in findings if f["code"].startswith(DIMENSION_PREFIX[dim])]
    dim_findings.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 9), f["code"]))
    controls = (
        _email_controls(payload, findings)
        if dim == "email"
        else _transport_controls(payload, findings)
    )
    _attach_finding_detail(controls, findings, payload)
    # The rail's severity summary counts exactly what the control list shows: one
    # entry per issue-bearing control, at the severity displayed on its row. A
    # control may map to several raw findings (e.g. DKIM); the row shows its
    # headline severity, so the summary must tally the same, or the two disagree.
    issues = [c for c in controls if c.get("finding_code")]
    return {
        **base,
        "measured": True,
        "grade": score["grade"],
        "score": _fmt_score(score["raw_score"]),
        "ruleset": score["ruleset_version"],
        "controls": controls,
        "finding_count": len(issues),
        "severity_counts": dict(Counter(c["severity"] for c in issues)),
        "findings": dim_findings,
    }


def finding_detail(scan_id: int, dim: str, code: str) -> dict | None:
    """One finding in full, for its own page (§ 4.4). Returns None if the scan,
    dimension or finding code does not match. Same enriched data (evidence,
    record, highlight) the in-place expansion uses — one source."""
    if not code.startswith(DIMENSION_PREFIX.get(dim, "\0")):
        return None
    collector = DIMENSION_COLLECTOR.get(dim)
    with _connect() as conn:
        scan = conn.execute(
            "SELECT s.id, s.started_at, d.domain FROM scans s "
            "JOIN domains d ON d.id = s.domain_id WHERE s.id = ?",
            (scan_id,),
        ).fetchone()
        if scan is None:
            return None
        frow = conn.execute(
            "SELECT code, severity, evidence_json, fix_hint_key "
            "FROM findings WHERE scan_id = ? AND code = ?",
            (scan_id, code),
        ).fetchone()
        if frow is None:
            return None
        score = conn.execute(
            "SELECT raw_score, grade FROM scores WHERE scan_id = ? AND dimension = ?",
            (scan_id, dim),
        ).fetchone()
        payload = {}
        if collector is not None:
            prow = conn.execute(
                "SELECT payload_json FROM scan_results WHERE scan_id = ? AND collector = ?",
                (scan_id, collector),
            ).fetchone()
            if prow is not None:
                payload = json.loads(prow["payload_json"])

    evidence = {}
    if frow["evidence_json"]:
        try:
            evidence = json.loads(frow["evidence_json"])
        except (ValueError, TypeError):
            evidence = {}
    record, highlight = _finding_record(code, payload)
    return {
        "scan_id": scan["id"],
        "domain": scan["domain"],
        "date_iso": scan["started_at"],
        "dim": dim,
        "grade": score["grade"] if score else None,
        "score": _fmt_score(score["raw_score"]) if score else None,
        "finding_code": code,
        "severity": frow["severity"],
        "evidence": evidence,
        "record": record,
        "highlight": highlight,
    }


def _attach_finding_detail(controls: list[dict], findings: list[dict], payload: dict) -> None:
    """Enrich each control that carries a finding with the data its in-place
    expansion needs: the parsed evidence (technical detail) and, where we have
    one, the actual record to show under "Your situation" with the problem token
    highlighted. All from stored raw data — nothing invented."""
    by_code = {f["code"]: f for f in findings}
    for c in controls:
        code = c.get("finding_code")
        if not code or code not in by_code:
            continue
        f = by_code[code]
        evidence = {}
        if f.get("evidence_json"):
            try:
                evidence = json.loads(f["evidence_json"])
            except (ValueError, TypeError):
                evidence = {}
        record, highlight = _finding_record(code, payload)
        c["evidence"] = evidence
        c["record"] = record
        c["highlight"] = highlight


def _finding_record(code: str, p: dict) -> tuple[str | None, str | None]:
    """The live record to show for a finding, and the token to flag in it."""
    if code.startswith("EMAIL_DMARC"):
        recs = p.get("dmarc", {}).get("records") or []
        return (recs[0], "p=none") if recs else (None, None)
    if code.startswith("EMAIL_SPF"):
        recs = p.get("spf", {}).get("records") or []
        term = p.get("spf", {}).get("parsed", {}).get("terminator") or {}
        return (recs[0], term.get("raw")) if recs else (None, None)
    return (None, None)


def _first_finding(findings: list[dict], codes: list[str]) -> dict | None:
    matches = [f for f in findings if f["code"] in codes]
    matches.sort(key=lambda f: SEVERITY_RANK.get(f["severity"], 9))
    return matches[0] if matches else None


def _control_row(
    key: str,
    name: str,
    name_key: str | None,
    present: bool,
    measured: bool,
    applicable: bool,
    finding: dict | None,
) -> dict:
    if not applicable:
        status = "na"
    elif not measured:
        status = "unmeasured"
    elif finding is not None:
        status = "info" if finding["severity"] == "info" else "fail"
    else:
        status = "pass" if present else "fail"

    is_issue = status in ("fail", "info") and finding is not None
    return {
        "key": key,
        "name": name,
        "name_key": name_key,
        "status": status,
        "severity": finding["severity"] if is_issue else None,
        "finding_code": finding["code"] if is_issue else None,
        "result_key": None if is_issue else _result_key(key, status),
    }


def _result_key(key: str, status: str) -> str:
    if status == "pass":
        return f"control.{key}.pass"
    return f"control.result.{status}"  # na / unmeasured (generic)


def _query_ok(payload: dict, section: str) -> bool:
    """A DNS section counts as measured unless the query errored (§ rule 6)."""
    q = payload.get(section, {}).get("query", {})
    return q.get("error_detail") is None and q.get("rcode") != "SERVFAIL"


def _email_controls(p: dict, findings: list[dict]) -> list[dict]:
    mx_present = bool(p.get("mx", {}).get("present"))
    mta = p.get("mta_sts", {})
    specs = [
        (
            "spf",
            "SPF",
            None,
            bool(p.get("spf", {}).get("present")),
            _query_ok(p, "spf"),
            True,
            [
                "EMAIL_NO_SPF",
                "EMAIL_SPF_MULTIPLE",
                "EMAIL_SPF_NEUTRAL",
                "EMAIL_SPF_PASS_ALL",
                "EMAIL_SPF_SOFTFAIL",
                "EMAIL_SPF_LOOKUP_LIMIT",
            ],
        ),
        (
            "dkim",
            "DKIM",
            None,
            bool(p.get("dkim", {}).get("found_selectors")),
            True,
            True,
            ["EMAIL_DKIM_NOT_OBSERVED", "EMAIL_DKIM_KEY_SHORT", "EMAIL_DKIM_FOUND"],
        ),
        (
            "dmarc",
            "DMARC",
            None,
            bool(p.get("dmarc", {}).get("present")),
            _query_ok(p, "dmarc"),
            True,
            [
                "EMAIL_NO_DMARC",
                "EMAIL_DMARC_INVALID",
                "EMAIL_DMARC_MULTIPLE",
                "EMAIL_DMARC_NO_RUA",
                "EMAIL_DMARC_PCT_PARTIAL",
                "EMAIL_DMARC_POLICY_NONE",
                "EMAIL_DMARC_POLICY_QUARANTINE",
                "EMAIL_DMARC_SUBDOMAIN_WEAK",
            ],
        ),
        ("mx", "MX", None, mx_present, _query_ok(p, "mx"), True, ["EMAIL_NO_MX"]),
        (
            "dnssec",
            "DNSSEC",
            None,
            bool(p.get("dnssec", {}).get("ds_present")),
            True,
            True,
            ["EMAIL_NO_DNSSEC"],
        ),
        (
            "caa",
            "CAA",
            None,
            bool(p.get("caa", {}).get("present")),
            _query_ok(p, "caa"),
            True,
            ["EMAIL_NO_CAA"],
        ),
        (
            "dane",
            "DANE",
            None,
            bool(p.get("dane", {}).get("present")),
            True,
            mx_present,
            ["EMAIL_NO_DANE", "EMAIL_DANE_WITHOUT_DNSSEC"],
        ),
        (
            "mta_sts",
            "MTA-STS",
            None,
            bool(mta.get("policy")) or bool(mta.get("dns", {}).get("present")),
            True,
            mx_present,
            ["EMAIL_NO_MTA_STS"],
        ),
        (
            "tls_rpt",
            "TLS-RPT",
            None,
            bool(p.get("tls_rpt", {}).get("present")),
            _query_ok(p, "tls_rpt"),
            mx_present,
            ["EMAIL_NO_TLS_RPT"],
        ),
    ]
    return [
        _control_row(
            key, name, name_key, present, measured, applicable, _first_finding(findings, codes)
        )
        for key, name, name_key, present, measured, applicable, codes in specs
    ]


def _transport_controls(p: dict, findings: list[dict]) -> list[dict]:
    http = p.get("http", {})
    tls = p.get("tls_versions", {})
    cert = p.get("certificate", {})
    hp = p.get("homepage", {})
    reachable = bool(hp.get("reachable"))
    supported = tls.get("supported") or []
    modern = any(v in ("TLSv1.2", "TLSv1.3") for v in supported)
    https_ok = bool(http.get("reached_https")) and not http.get("cleartext_after_https")
    cert_ok = bool(cert.get("verified")) and bool(cert.get("hostname_in_san"))
    specs = [
        (
            "https",
            "control.https.name",
            https_ok,
            "reached_https" in http,
            True,
            ["TRANSPORT_NO_HTTPS", "TRANSPORT_CLEARTEXT_REDIRECT"],
        ),
        (
            "tls",
            "control.tls.name",
            modern,
            bool(supported) or bool(tls.get("probed")),
            True,
            ["TRANSPORT_TLS_OUTDATED", "TRANSPORT_TLS_LEGACY"],
        ),
        (
            "cert",
            "control.cert.name",
            cert_ok,
            cert.get("verified") is not None or bool(cert.get("obtained")),
            True,
            ["TRANSPORT_CERT_INVALID", "TRANSPORT_CERT_EXPIRING"],
        ),
        (
            "hsts",
            "control.hsts.name",
            bool(hp.get("hsts", {}).get("present")),
            reachable,
            True,
            ["TRANSPORT_NO_HSTS", "TRANSPORT_HSTS_SHORT", "TRANSPORT_HSTS_NO_INCLUDESUBDOMAINS"],
        ),
        (
            "headers",
            "control.headers.name",
            bool(hp.get("security_headers")),
            reachable,
            True,
            ["TRANSPORT_MISSING_SECURITY_HEADERS"],
        ),
        (
            "securitytxt",
            "control.securitytxt.name",
            bool(p.get("security_txt", {}).get("present")),
            True,
            True,
            ["TRANSPORT_NO_SECURITY_TXT"],
        ),
    ]
    return [
        _control_row(
            key, name_key, name_key, present, measured, applicable, _first_finding(findings, codes)
        )
        for key, name_key, present, measured, applicable, codes in specs
    ]


# --------------------------------------------------------------- sector view


def sector_comparison(scan_id: int) -> dict | None:
    """This scan's dimension grades set against its sector's real distribution.

    Per dimension (not a composite — none exists yet), we compare the domain's
    grade to the latest scan of every labelled peer in the same sector. All real
    aggregates; peers are never named (§ 4.5). Returns None if the scan is absent,
    and ``sector_known=False`` when the domain has no labelled sector to compare.
    """
    with _connect() as conn:
        scan = conn.execute(
            "SELECT s.id, s.started_at, d.domain, d.sector FROM scans s "
            "JOIN domains d ON d.id = s.domain_id WHERE s.id = ?",
            (scan_id,),
        ).fetchone()
        if scan is None:
            return None
        sector = scan["sector"]
        base = {
            "scan_id": scan["id"],
            "domain": scan["domain"],
            "date_iso": scan["started_at"],
            "sector": sector,
        }
        if sector not in LABELLED_SECTORS:
            return {**base, "sector_known": False, "dimensions": []}

        own = {
            r["dimension"]: r
            for r in conn.execute(
                "SELECT dimension, raw_score, grade FROM scores WHERE scan_id = ?", (scan_id,)
            )
        }
        dims = []
        for dim in ("email", "transport"):
            o = own.get(dim)
            if o is None or o["raw_score"] is None:
                continue  # no numeric score to place on the distribution
            rows = conn.execute(
                """
                WITH latest AS (
                    SELECT sc.id,
                           ROW_NUMBER() OVER (
                               PARTITION BY sc.domain_id
                               ORDER BY sc.started_at DESC, sc.id DESC
                           ) AS rn
                    FROM scans sc JOIN domains d ON d.id = sc.domain_id
                    WHERE d.sector = ?
                )
                SELECT s.raw_score AS raw_score, s.grade AS grade
                FROM latest l JOIN scores s ON s.scan_id = l.id AND s.dimension = ?
                WHERE l.rn = 1
                """,
                (sector, dim),
            ).fetchall()
            # Insufficient-data peers (grade "I", no numeric score) cannot be
            # ranked, so they are not part of the comparison population.
            graded = [r for r in rows if r["raw_score"] is not None]
            n = len(graded)
            if n == 0:
                continue
            scores = [r["raw_score"] for r in graded]
            avg = sum(scores) / n
            better = sum(1 for s in scores if s < o["raw_score"])
            counts = Counter(r["grade"] for r in graded)
            ordered = [(g, counts[g]) for g in GRADE_ORDER if counts.get(g)]
            ordered += [(g, c) for g, c in counts.items() if g not in GRADE_ORDER]
            max_count = max(c for _, c in ordered)
            dims.append(
                {
                    "key": dim,
                    "num": DIMENSION_NUM[dim],
                    "grade": o["grade"],
                    "score": _fmt_score(o["raw_score"]),
                    "sector_avg": _fmt_score(avg),
                    "total": n,
                    "better_pct": round(100 * better / n),
                    "max_count": max_count,
                    "dist": [
                        {
                            "grade": g,
                            "count": c,
                            "pct": round(100 * c / max_count),
                            "is_own": g == o["grade"],
                        }
                        for g, c in ordered
                    ],
                }
            )
        return {**base, "sector_known": True, "dimensions": dims}
