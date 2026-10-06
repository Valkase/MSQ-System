"""
Message-key translation (task plan 2.5): "Externalize all UI-facing
strings ... no hardcoded English text in logic or GUI code".

Design: every user-facing string in the logic layer is raised as a
message KEY (e.g. "validation.required"), not literal English text.
`translate()` resolves a key + the current locale into the actual
displayed string by reading locales/<locale>/messages.json. The GUI
layer will do the same for its own strings once Phase 4 exists.

Locale is a process-wide setting (`set_locale`/`get_locale`), not a
per-call argument threaded through every function — this is a single
desktop app per front-desk PC (design doc Section 3), so "the app's
current language" is a reasonable global for one process, the same way
a real desktop app's language setting works. Tests must not rely on the
global staying at its default; see tests/conftest.py's `locale` fixture,
which resets it after every test.

Fallback behavior, deliberately layered so a missing translation is
never a hard crash:
  1. exact key in the requested locale's catalog
  2. same key in the English catalog (English is the baseline/reference
     translation; Arabic strings get filled in progressively)
  3. the raw key itself, wrapped in "??" markers — visible enough in the
     UI during development to get noticed and fixed, but never an
     exception that would take down a receptionist's workflow over a
     missing string.
"""

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "ar")

from app_paths import resource_path
_LOCALES_DIR = resource_path("locales")

_current_locale = DEFAULT_LOCALE


def get_locale() -> str:
    """The process-wide active locale (defaults to 'en')."""
    return _current_locale


def set_locale(locale: str) -> None:
    """
    Switch the process-wide active locale — called by the Phase 4
    language switcher. Raises ValueError for anything outside
    SUPPORTED_LOCALES rather than silently falling back, since a typo'd
    locale code is a programming error worth surfacing immediately.
    """
    global _current_locale
    if locale not in SUPPORTED_LOCALES:
        raise ValueError(
            f"Unsupported locale {locale!r}. Supported locales: {SUPPORTED_LOCALES}."
        )
    _current_locale = locale


@lru_cache(maxsize=None)
def _load_catalog(locale: str) -> dict:
    """
    Read locales/<locale>/messages.json into a flat {key: template}
    dict. Cached (@lru_cache) since these files don't change while the
    app is running — call _load_catalog.cache_clear() in tests if a
    catalog file is edited mid-test-run.
    """
    path = _LOCALES_DIR / locale / "messages.json"
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def translate(key: str, **params) -> str:
    """
    Resolve a message key to a display string in the current locale,
    substituting `**params` into the template with str.format(). See
    the module docstring for the fallback chain (locale -> English ->
    raw key).

    Missing placeholders in `params` don't raise — a malformed message
    should degrade to something visible, not crash the action that
    triggered it.
    """
    locale = get_locale()
    template = _load_catalog(locale).get(key)

    if template is None and locale != DEFAULT_LOCALE:
        template = _load_catalog(DEFAULT_LOCALE).get(key)

    if template is None:
        return f"??{key}??"

    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


# Short alias — used pervasively throughout the logic layer, so a short
# name matters for readability (`t("validation.required", field=...)`
# reads far better inline than `translate(...)` at every call site).
t = translate