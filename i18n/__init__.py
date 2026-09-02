"""
Localization (task plan 2.5). Public API of this package:

    from i18n import t, get_locale, set_locale
    from i18n import format_currency, format_date, format_datetime, format_number

`t` (alias of `translate`) resolves a message KEY to display text in the
current locale — see i18n/translator.py for the fallback chain, and
locales/en/messages.json + locales/ar/messages.json for the catalogs.
The format_* functions are locale-aware number/date/currency rendering
via Babel — see i18n/formatting.py.
"""

from i18n.formatting import (
    DEFAULT_CURRENCY,
    format_currency,
    format_date,
    format_datetime,
    format_number,
)
from i18n.translator import DEFAULT_LOCALE, SUPPORTED_LOCALES, get_locale, set_locale, t, translate

__all__ = [
    "t",
    "translate",
    "get_locale",
    "set_locale",
    "SUPPORTED_LOCALES",
    "DEFAULT_LOCALE",
    "format_currency",
    "format_date",
    "format_datetime",
    "format_number",
    "DEFAULT_CURRENCY",
]