"""
Unit tests for i18n/ (task plan 2.5): the translate() fallback chain,
and that number/date/currency formatting actually differs correctly
between English and Arabic (task plan 2.5's "Confirm number, date, and
currency formatting behave correctly in both languages"). Also confirms
the logic layer's error messages — not just the i18n module in isolation
— actually change language when the active locale changes, since a
translation system nobody's error messages go through doesn't localize
anything.

Uses the `_reset_locale` autouse fixture from conftest.py, so tests here
that call set_locale("ar") never leak into other test files.
"""

from datetime import date
from decimal import Decimal

import pytest

from i18n import format_currency, format_date, format_number, get_locale, set_locale, t
from logic.errors import PermissionDeniedError, ValidationError
from logic.permissions import Permission, require_permission
from logic.validation import validate_required_text

# --- translate() fallback chain ----------------------------------------------------


def test_default_locale_is_english():
    assert get_locale() == "en"


def test_translate_switches_with_set_locale():
    en_text = t("fields.full_name")
    set_locale("ar")
    ar_text = t("fields.full_name")

    assert en_text == "Full name"
    assert ar_text != en_text
    assert ar_text  # non-empty


def test_translate_missing_key_returns_visible_marker():
    assert t("this.key.does.not.exist.anywhere") == "??this.key.does.not.exist.anywhere??"


def test_translate_falls_back_to_english_when_arabic_catalog_lacks_a_key(monkeypatch):
    import i18n.translator as translator_module

    def fake_load_catalog(locale: str) -> dict:
        if locale == "en":
            return {"some.key": "English text"}
        return {}  # Arabic catalog deliberately missing this key

    monkeypatch.setattr(translator_module, "_load_catalog", fake_load_catalog)
    set_locale("ar")

    assert t("some.key") == "English text"


def test_set_locale_rejects_unsupported_locale():
    with pytest.raises(ValueError):
        set_locale("fr")
    # rejecting an unsupported locale must not have half-applied it
    assert get_locale() == "en"


def test_translate_substitutes_named_parameters():
    set_locale("en")
    message = t("validation.max_length", field="Full name", max_length=150)
    assert message == "Full name must be 150 characters or fewer."


# --- the logic layer actually localizes, not just i18n in isolation ---------------


def test_validation_error_message_changes_with_locale():
    set_locale("en")
    with pytest.raises(ValidationError) as exc_en:
        validate_required_text("", "fields.full_name", max_length=150)

    set_locale("ar")
    with pytest.raises(ValidationError) as exc_ar:
        validate_required_text("", "fields.full_name", max_length=150)

    assert str(exc_en.value) == "Full name is required."
    assert str(exc_ar.value) != str(exc_en.value)
    assert "??" not in str(exc_ar.value)


def test_permission_denied_message_changes_with_locale(receptionist_user):
    set_locale("en")
    with pytest.raises(PermissionDeniedError) as exc_en:
        require_permission(receptionist_user, Permission.MANAGE_DOCTORS)

    set_locale("ar")
    with pytest.raises(PermissionDeniedError) as exc_ar:
        require_permission(receptionist_user, Permission.MANAGE_DOCTORS)

    assert "manage doctors" in str(exc_en.value)
    assert str(exc_ar.value) != str(exc_en.value)
    assert "??" not in str(exc_ar.value)


# --- number / date / currency formatting (Babel) -----------------------------------


def test_currency_formatting_differs_by_locale_but_both_are_correct():
    amount = Decimal("1234.50")

    en_result = format_currency(amount, locale="en")
    ar_result = format_currency(amount, locale="ar")

    assert "EGP" in en_result
    assert "1,234.50" in en_result
    assert "ج.م" in ar_result  # Arabic abbreviation for Egyptian pound
    assert en_result != ar_result


def test_date_formatting_differs_by_locale():
    value = date(2026, 9, 2)

    en_result = format_date(value, locale="en", format="long")
    ar_result = format_date(value, locale="ar", format="long")

    assert "September" in en_result
    assert "سبتمبر" in ar_result  # Arabic for "September"
    assert en_result != ar_result


def test_number_formatting_uses_grouping_separator_in_both_locales():
    value = Decimal("1234.56")

    en_result = format_number(value, locale="en")
    ar_result = format_number(value, locale="ar")

    assert "1,234.56" == en_result
    # ar_EG (CLDR) also groups with Western digits/comma for this context —
    # confirm it's still a correctly grouped number, not asserting the
    # exact same string as a coincidence.
    assert "1,234.56" in ar_result or "١٬٢٣٤٫٥٦" in ar_result


def test_format_functions_default_to_the_current_active_locale():
    set_locale("ar")
    active_locale_result = format_date(date(2026, 9, 2), format="long")
    explicit_ar_result = format_date(date(2026, 9, 2), format="long", locale="ar")

    assert active_locale_result == explicit_ar_result