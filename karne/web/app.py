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
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined

from karne.web.i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    format_long_date,
    get_translator,
    verify_parity,
)

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
    files = [STATIC_DIR / "tokens.css", STATIC_DIR / "app.css"]
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
def home(request: Request, lang: str) -> HTMLResponse:
    # Step-1 scaffold page: exercises the base template, both bands, the fonts
    # and the Turkish glyph check. Replaced by the real home page in a later
    # session.
    lang = _require_lang(lang)
    return templates.TemplateResponse(request, "scaffold.html", _context(request, lang))


def _demo_nav(lang: str) -> dict:
    """Left-nav context for the step-3 shell preview.

    Real values from webkarne.com (scan 29545): scanned 2026-09-12, with email
    and transport measured; privacy and tech have no collector yet, so they show
    the muted "not measured in this scan" state (§ 3.4 / § 8.2). No fabricated
    data — this preview is replaced by the real Overview screen later.
    """
    return {
        "domain": "webkarne.com",
        "date": format_long_date("2026-09-12", lang),
        "active": "overview",
        "dimensions": [
            {"key": "email", "label": "dim.email.nav", "num": "01", "measured": True},
            {"key": "transport", "label": "dim.transport.nav", "num": "02", "measured": True},
            {"key": "privacy", "label": "dim.privacy.nav", "num": "03", "measured": False},
            {"key": "tech", "label": "dim.tech.nav", "num": "04", "measured": False},
        ],
    }


@app.get("/{lang}/kabuk", response_class=HTMLResponse, include_in_schema=False)
def shell_preview(request: Request, lang: str) -> HTMLResponse:
    # Temporary step-3 preview of the analysis shell grid. Removed with the real
    # Overview screen.
    lang = _require_lang(lang)
    return templates.TemplateResponse(
        request, "_shell_demo.html", _context(request, lang, nav=_demo_nav(lang))
    )


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
