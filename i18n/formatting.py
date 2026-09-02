"""
Number, date, and currency formatting (task plan 2.5: "Confirm number,
date, and currency formatting behave correctly in both languages").

Built on Babel (https://babel.pocoo.org/) rather than hand-rolled
formatting rules — locale-correct grouping separators, currency symbol
placement, and month names are exactly the kind of thing that's easy to
get subtly wrong by hand and Babel already gets right from CLDR data.

DEFAULT_CURRENCY is EGP (Egyptian pound) since this clinic is a single
Egypt-based location (design doc Section 3) — override per call if a
future deployment needs a different currency.
"""

from datetime import date, datetime
from decimal import Decimal

from babel.dates import format_date as _babel_format_date
from babel.dates import format_datetime as _babel_format_datetime
from babel.numbers import format_currency as _babel_format_currency
from babel.numbers import format_decimal as _babel_format_decimal

from i18n.translator import get_locale

DEFAULT_CURRENCY = "EGP"

# App locale codes ("en"/"ar", matching locales/<code>/) mapped to the
# closer, region-specific Babel/CLDR locale identifiers — gives correct
# Egypt-specific conventions (e.g. ar_EG) rather than a generic Arabic
# default that might assume a different region's formatting.
_BABEL_LOCALE = {
    "en": "en_US",
    "ar": "ar_EG",
}


def _babel_locale(locale: str | None) -> str:
    locale = locale or get_locale()
    return _BABEL_LOCALE.get(locale, locale)


def format_number(value: Decimal | int | float, *, locale: str | None = None) -> str:
    """Locale-correct grouping/decimal separators for a plain number (not currency)."""
    return _babel_format_decimal(value, locale=_babel_locale(locale))


def format_currency(
    amount: Decimal, *, currency: str = DEFAULT_CURRENCY, locale: str | None = None
) -> str:
    """
    Locale-correct currency formatting — symbol/code placement, digit
    grouping, and decimal separator all follow the active locale's
    convention. Always pass a Decimal (never a float — see
    logic/validation.py's "Decimal throughout" rule); Babel accepts it
    directly without any float round-trip.
    """
    return _babel_format_currency(amount, currency, locale=_babel_locale(locale))


def format_date(value: date, *, locale: str | None = None, format: str = "medium") -> str:
    """
    Locale-correct date formatting. `format` is one of Babel's presets:
    'short', 'medium' (default), 'long', 'full'.
    """
    return _babel_format_date(value, format=format, locale=_babel_locale(locale))


def format_datetime(value: datetime, *, locale: str | None = None, format: str = "medium") -> str:
    """Same as format_date but for a full timestamp (e.g. an audit_log entry's created_at)."""
    return _babel_format_datetime(value, format=format, locale=_babel_locale(locale))