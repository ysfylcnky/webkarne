"""Translation loading for the WebKarne interface.

Every user-facing string comes from a translation file (PLAN.md K-08); no string
is hard-coded in a template. Files live in ``translations/<lang>.json`` as a flat
map of dotted keys to text, so ``tr`` and ``en`` share one key set.

Every language file carries the same flat set of dotted keys. ``verify_parity``
enforces that at startup — there is no build step, so a mismatched or missing
key set must fail the moment the app loads, not render blank later (K-08).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"

DEFAULT_LANG = "tr"
SUPPORTED_LANGS = ("tr", "en")


def normalize_lang(lang: str) -> str:
    """Return a supported language code, falling back to the default."""
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


@lru_cache(maxsize=len(SUPPORTED_LANGS))
def _load(lang: str) -> dict[str, str]:
    # normalize_lang guarantees a supported code; a genuinely missing file is a
    # packaging error and should surface as FileNotFoundError, not fall back.
    path = TRANSLATIONS_DIR / f"{normalize_lang(lang)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def verify_parity() -> None:
    """Fail loudly if the language files do not share one key set (K-08).

    Called at app import so a translation gap stops startup instead of leaking
    an empty string — or a wrong-language fallback — into a rendered page.
    """
    key_sets = {lang: set(_load(lang)) for lang in SUPPORTED_LANGS}
    reference = key_sets[DEFAULT_LANG]
    problems: list[str] = []
    for lang, keys in key_sets.items():
        if lang == DEFAULT_LANG:
            continue
        missing = reference - keys
        extra = keys - reference
        if missing:
            problems.append(f"{lang!r} is missing keys: {sorted(missing)}")
        if extra:
            problems.append(f"{lang!r} has keys not in {DEFAULT_LANG!r}: {sorted(extra)}")
    if problems:
        raise RuntimeError("Translation parity failed — " + "; ".join(problems))


# Long-form month names for the "12 Eylül 2026" date style (DESIGN-SYSTEM § 12).
_MONTHS: dict[str, tuple[str, ...]] = {
    "tr": (
        "Ocak",
        "Şubat",
        "Mart",
        "Nisan",
        "Mayıs",
        "Haziran",
        "Temmuz",
        "Ağustos",
        "Eylül",
        "Ekim",
        "Kasım",
        "Aralık",
    ),
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
}


def format_long_date(iso: str, lang: str) -> str:
    """Format an ISO date/datetime as "12 Eylül 2026" / "12 September 2026"."""
    from datetime import datetime

    dt = datetime.fromisoformat(iso)
    months = _MONTHS[normalize_lang(lang)]
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


class Translator:
    """Callable translator for one language.

    ``t(key)`` raises loudly on a missing key — an untranslated string must never
    reach the page (K-08). ``t.has(key)`` / ``t.get(key)`` are for genuinely
    optional content (e.g. a finding section that only some findings carry), so
    templates can decide whether to render a section rather than fail.
    """

    def __init__(self, data: dict[str, str], lang: str) -> None:
        self._data = data
        self._lang = lang

    def __call__(self, key: str) -> str:
        try:
            return self._data[key]
        except KeyError as exc:
            raise KeyError(f"Missing translation key {key!r} for language {self._lang!r}") from exc

    def has(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)


def get_translator(lang: str) -> Callable[[str], str]:
    """Return the :class:`Translator` for one language."""
    return Translator(_load(normalize_lang(lang)), normalize_lang(lang))
