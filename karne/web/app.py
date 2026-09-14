"""WebKarne FastAPI application — server-side rendered UI.

Sprint 3 · Session 2. Step 1 wires the base template, top/bottom bands and the
static mount (tokens.css lives at ``karne/web/static/tokens.css``). Full
language-switch routing, the analysis shell and the component catalog arrive in
later steps.

Run locally:  uv run uvicorn karne.web.app:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

from karne.web import query, reports
from karne.web.i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    format_long_date,
    get_translator,
    verify_parity,
)

# Dimension URL slugs — same in both languages (§ 9).
DIM_SLUG = {"email": "eposta", "transport": "aktarim", "privacy": "gizlilik", "tech": "teknoloji"}
SLUG_DIM = {slug: dim for dim, slug in DIM_SLUG.items()}

# A query is scoped to what the visitor asked about (§ 4.1): an email query shows
# only the email dimension; a domain query shows only the web/domain dimensions
# (transport now, privacy + tech once their collectors land) — never a mix, and
# never email-first in a domain report. "all" is the full four-dimension report,
# reached from the left-nav "overview" link and the demo catalog.
SCOPE_DIMS = {
    "email": ("email",),
    "web": ("transport", "privacy", "tech"),
}


def _scope_for_dim(dim: str) -> str:
    """The scope a single-dimension page belongs to (email vs. the web report)."""
    return "email" if dim == "email" else "web"


# Every language file must share one key set before we serve a single page.
verify_parity()

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"

app = FastAPI(title="WebKarne", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
# A missing translation key or context variable must fail loudly, not render
# blank (K-08). See i18n.get_translator.
templates.env.undefined = StrictUndefined


def _require_lang(lang: str) -> str:
    """Accept only supported language codes; anything else is a 404.

    This keeps stray paths (favicon.ico, bots) out of the language routes
    instead of silently serving them the default language.
    """
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=404)
    return lang


def _alt_lang_urls(request: Request) -> dict[str, str]:
    """Same page in every language — only the URL prefix changes (§ 9).

    Slugs are identical across languages, so switching swaps the first path
    segment and keeps the rest (and the query string).
    """
    _, _, rest = request.url.path.lstrip("/").partition("/")
    query = f"?{request.url.query}" if request.url.query else ""
    return {lang: f"/{lang}/{rest}{query}" for lang in SUPPORTED_LANGS}


def _asset_version() -> str:
    """Cache-busting token from the newest static file's mtime.

    Appended to CSS links so an edited stylesheet is never served stale from the
    browser cache; also gives production long-lived caching a safe key.
    """
    files = [STATIC_DIR / "tokens.css", STATIC_DIR / "app.css", STATIC_DIR / "app.js"]
    latest = max((f.stat().st_mtime for f in files if f.exists()), default=0.0)
    return str(int(latest))


def _context(request: Request, lang: str, **extra: object) -> dict:
    return {
        "request": request,
        "lang": lang,
        "t": get_translator(lang),
        "alt_lang_urls": _alt_lang_urls(request),
        "asset_version": _asset_version(),
        **extra,
    }


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url=f"/{DEFAULT_LANG}/")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    # No favicon asset yet; answer explicitly so the request never falls through
    # to the language routes.
    return Response(status_code=204)


@app.get("/{lang}/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request, lang: str, hata: str = "") -> HTMLResponse:
    # Home page (§ 4.1): the domain/email query panels. `hata` carries a
    # validation error type back from the resolve route.
    lang = _require_lang(lang)
    return templates.TemplateResponse(request, "home.html", _context(request, lang, error=hata))


def _validate_query(tur: str, raw: str) -> tuple[str | None, str]:
    """Turn a typed domain/email into a clean domain + the error type on failure."""
    if tur == "eposta":
        return query.extract_email_domain(raw), "email"
    return query.normalize_domain(raw), "domain"


@app.get("/{lang}/git", response_class=HTMLResponse, include_in_schema=False)
def resolve_query(request: Request, lang: str, tur: str = "alan", q: str = ""):
    # Validate the typed input, then show the "measuring…" screen (§ 8.1). The
    # scan itself runs behind that screen via /tara, so the visitor sees progress
    # instead of a blank wait. Invalid input bounces back to the home form.
    lang = _require_lang(lang)
    tur = "eposta" if tur == "eposta" else "alan"
    domain, error_type = _validate_query(tur, q)
    if domain is None:
        return RedirectResponse(url=f"/{lang}/?hata={error_type}", status_code=303)
    run = f"/{lang}/tara?d={domain}&tur={tur}"
    ctx = _context(request, lang, domain=domain, tur=tur, run_url=run, run_json_url=f"{run}&json=1")
    return templates.TemplateResponse(request, "scanning.html", ctx)


@app.get("/{lang}/tara", include_in_schema=False)
def run_scan(request: Request, lang: str, d: str = "", tur: str = "alan", json: int = 0):
    # Run a FRESH scan of the domain (never a stored one — the visitor asked to
    # scan it now) and hand back the report URL, scoped to what they asked about:
    # an email query lands on the email dimension; a domain query on the web
    # report. Called by the scanning screen's fetch (json=1); the <noscript>
    # meta-refresh falls through to the plain 303 redirect.
    lang = _require_lang(lang)
    domain = query.normalize_domain(d)
    if domain is None:
        return RedirectResponse(url=f"/{lang}/?hata=domain", status_code=303)
    scan_id = query.run_live_scan(domain)
    if tur == "eposta":
        target = f"/{lang}/analiz/{scan_id}/eposta"
    else:
        target = f"/{lang}/analiz/{scan_id}?kapsam=web"
    if json:
        return JSONResponse({"redirect": target})
    return RedirectResponse(url=target, status_code=303)


def _report_nav(lang: str, report: dict, active: str, scope: str = "all") -> dict:
    """Left-nav context built from a report (§ 3.4). URLs are real routes.

    ``scope`` restricts the listed dimensions so an email report never lists the
    web dimensions and vice-versa; "all" lists all four (the full report).
    """
    base = f"/{lang}/analiz/{report['scan_id']}"
    keep = SCOPE_DIMS.get(scope)
    overview_url = base if keep is None else f"{base}?kapsam={scope}"
    dims = [d for d in report["dimensions"] if keep is None or d["key"] in keep]
    return {
        "domain": report["domain"],
        "date": format_long_date(report["date_iso"], lang),
        "active": active,
        "scope": scope,
        "home_url": f"/{lang}/",
        "overview_url": overview_url,
        # Query-free base for building child URLs (findings, breadcrumbs). Never
        # append a path onto overview_url — under a scope it carries a ?kapsam=…
        # query, and "…?kapsam=web/eposta/slug" would route back to the overview.
        "report_url": base,
        "sector_url": f"{base}/sektor",
        "dimensions": [
            {
                "key": d["key"],
                "num": d["num"],
                "measured": d["measured"],
                "label": f"dim.{d['key']}.nav",
                "url": f"{base}/{DIM_SLUG[d['key']]}",
            }
            for d in dims
        ],
    }


def _scope_report(report: dict, scope: str) -> dict:
    """A copy of the report showing only the scope's dimensions and findings.

    A domain query must not surface email results (and vice-versa), and the
    partial-measurement count must reflect only the dimensions in scope. "all"
    returns the report unchanged.
    """
    keep = SCOPE_DIMS.get(scope)
    if keep is None:
        return report
    prefixes = tuple(reports.DIMENSION_PREFIX[k] for k in keep if k in reports.DIMENSION_PREFIX)
    dims = [d for d in report["dimensions"] if d["key"] in keep]
    findings = [f for f in report["findings"] if f["code"].startswith(prefixes)]
    return {
        **report,
        "dimensions": dims,
        "measured_count": sum(1 for d in dims if d["measured"]),
        "total_dimensions": len(dims),
        "findings": findings,
        "featured_findings": findings[:3],
        "finding_count": len(findings),
    }


@app.get("/{lang}/analiz/{scan_id}", response_class=HTMLResponse, include_in_schema=False)
def overview(request: Request, lang: str, scan_id: int, kapsam: str = "") -> HTMLResponse:
    # Overview screen (§ 4.2): the frozen report for one scan. `kapsam` scopes it
    # to what the visitor searched — "web" (domain query) or "email" — so the
    # report never mixes the two; empty means the full four-dimension report.
    lang = _require_lang(lang)
    report = reports.load_report(scan_id)
    if report is None:
        raise HTTPException(status_code=404)
    scope = kapsam if kapsam in SCOPE_DIMS else "all"
    scoped = _scope_report(report, scope)
    ctx = _context(request, lang, report=scoped, nav=_report_nav(lang, scoped, "overview", scope))
    return templates.TemplateResponse(request, "overview.html", ctx)


@app.get(
    "/{lang}/analiz/{scan_id}/{dim_slug}", response_class=HTMLResponse, include_in_schema=False
)
def dimension(request: Request, lang: str, scan_id: int, dim_slug: str) -> HTMLResponse:
    # Dimension screen (§ 4.3). Sector (S5) will register its own route before
    # this generic one; for now an unknown slug is a 404.
    lang = _require_lang(lang)
    if dim_slug == "sektor":
        return _sector_page(request, lang, scan_id)
    dim = SLUG_DIM.get(dim_slug)
    if dim is None:
        raise HTTPException(status_code=404)
    report = reports.load_report(scan_id)
    if report is None:
        raise HTTPException(status_code=404)
    detail = reports.dimension_detail(scan_id, dim)
    ctx = _context(
        request,
        lang,
        report=report,
        detail=detail,
        nav=_report_nav(lang, report, dim, _scope_for_dim(dim)),
        dim_label=f"dim.{dim}.nav",
    )
    return templates.TemplateResponse(request, "dimension.html", ctx)


def _sector_page(request: Request, lang: str, scan_id: int) -> HTMLResponse:
    # Sector comparison (§ 4.5): this scan's dimension grades against the real
    # distribution of its labelled sector. Peers are aggregated, never named.
    report = reports.load_report(scan_id)
    sector = reports.sector_comparison(scan_id)
    if report is None or sector is None:
        raise HTTPException(status_code=404)
    ctx = _context(
        request,
        lang,
        report=report,
        sector=sector,
        nav=_report_nav(lang, report, "sector"),
    )
    return templates.TemplateResponse(request, "sector.html", ctx)


@app.get(
    "/{lang}/analiz/{scan_id}/{dim_slug}/{finding_slug}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def finding_page(
    request: Request, lang: str, scan_id: int, dim_slug: str, finding_slug: str
) -> HTMLResponse:
    # Full finding page (§ 4.4): the same finding content as the in-place
    # expansion, in a shareable full-page container with the sticky anchor strip.
    lang = _require_lang(lang)
    dim = SLUG_DIM.get(dim_slug)
    if dim is None:
        raise HTTPException(status_code=404)
    code = finding_slug.upper().replace("-", "_")  # slug ↔ code is a clean bijection
    finding = reports.finding_detail(scan_id, dim, code)
    report = reports.load_report(scan_id)
    if finding is None or report is None:
        raise HTTPException(status_code=404)
    ctx = _context(
        request,
        lang,
        report=report,
        finding=finding,
        nav=_report_nav(lang, report, dim, _scope_for_dim(dim)),
        dim_label=f"dim.{dim}.nav",
        dim_slug=dim_slug,
    )
    return templates.TemplateResponse(request, "finding_full.html", ctx)


# webkarne.com (scan 29545) findings, ordered high → medium → low → info. This
# domain has no high-severity finding, which is itself real.
_CATALOG_FINDINGS: list[tuple[str, str]] = [
    ("EMAIL_DMARC_POLICY_NONE", "medium"),
    ("EMAIL_SPF_SOFTFAIL", "medium"),
    ("TRANSPORT_MISSING_SECURITY_HEADERS", "medium"),
    ("TRANSPORT_NO_HSTS", "medium"),
    ("EMAIL_NO_MTA_STS", "low"),
    ("EMAIL_NO_TLS_RPT", "low"),
    ("EMAIL_DKIM_NOT_OBSERVED", "info"),
    ("TRANSPORT_NO_SECURITY_TXT", "info"),
]


@app.get("/{lang}/stil", response_class=HTMLResponse, include_in_schema=False)
def catalog(request: Request, lang: str) -> HTMLResponse:
    # Live component catalog (DESIGN-SYSTEM § 14). Stays open in production; the
    # thesis appendix screenshots come from here.
    lang = _require_lang(lang)
    return templates.TemplateResponse(
        request, "catalog.html", _context(request, lang, findings=_CATALOG_FINDINGS)
    )


# Static content pages reached from the top nav (§ 3.3). Prose lives entirely in
# the translation files; `sections` is how many headed sections each page has, so
# the article template can loop them. `sektor` is an honest "in preparation"
# landing until the sector-comparison feature (S5) lands — it keeps the top nav
# from 404-ing rather than faking data.
INFO_PAGES: dict[str, dict[str, object]] = {
    "metodoloji": {"sections": 6, "nav": "nav.methodology"},
    "hakkinda": {"sections": 4, "nav": "nav.about"},
    "acik-veri": {"sections": 4, "nav": "nav.open_data"},
    "sektor": {"sections": 2, "nav": "nav.sector_analyses"},
}
# The trio cross-linked at the foot of each info page (the sektor placeholder is
# not advertised here).
_RELATED_SLUGS = ["metodoloji", "hakkinda", "acik-veri"]


def _make_page_route(slug: str, sections: int):
    def page(request: Request, lang: str) -> HTMLResponse:
        lang = _require_lang(lang)
        related = [{"slug": s, "label": INFO_PAGES[s]["nav"]} for s in _RELATED_SLUGS if s != slug]
        ctx = _context(request, lang, slug=slug, sections=sections, related=related)
        return templates.TemplateResponse(request, "article.html", ctx)

    return page


for _slug, _spec in INFO_PAGES.items():
    app.add_api_route(
        f"/{{lang}}/{_slug}",
        _make_page_route(_slug, int(_spec["sections"])),
        methods=["GET"],
        response_class=HTMLResponse,
        include_in_schema=False,
    )
