"""
Shared field-level validation helpers.

Kept deliberately separate from the models (which just store data) and
from any single entity's logic module, since phone/email/name-shaped
fields are reused across patients, doctors, and users. Every validator
either returns a cleaned value or raises logic.errors.ValidationError —
they never touch the database.

Localization (task plan 2.5): every message here is built via i18n.t()
from a message key, never a literal English string, so it displays in
whatever locale is currently active (see i18n/translator.py and
locales/en|ar/messages.json). Callers pass a FIELD KEY, not a literal
field name — e.g. validate_required_text(name, "fields.full_name", ...)
— so the field name in the error message is translated too.
"""

import re
from decimal import Decimal, InvalidOperation

from i18n import t
from logic.errors import ValidationError

# Accepts digits with optional leading +, and optional spaces/hyphens as
# separators (e.g. "010 000 0001", "+20-100-000-0001"). Deliberately
# permissive on format since this clinic has one country's phone numbers
# in practice, not a general international validator.
_PHONE_ALLOWED_CHARS_RE = re.compile(r"^[0-9+\-\s]+$")
_PHONE_DIGITS_MIN = 7
_PHONE_DIGITS_MAX = 15

# Simple, intentionally non-exhaustive email shape check — good enough to
# catch typos, not meant to be a full RFC 5322 validator.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_required_text(value: str | None, field_key: str, *, max_length: int) -> str:
    """
    Strip, require non-empty, and enforce a max length. Returns the
    cleaned value. `field_key` is a message key (e.g. "fields.full_name"),
    translated into the error message so it matches the active locale.
    """
    cleaned = (value or "").strip()
    field_name = t(field_key)
    if not cleaned:
        raise ValidationError(t("validation.required", field=field_name))
    if len(cleaned) > max_length:
        raise ValidationError(t("validation.max_length", field=field_name, max_length=max_length))
    return cleaned


def validate_optional_text(value: str | None, field_key: str, *, max_length: int) -> str | None:
    """Same as validate_required_text but allows None/empty (returns None in that case)."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValidationError(
            t("validation.max_length", field=t(field_key), max_length=max_length)
        )
    return cleaned


def validate_phone(phone: str | None) -> str:
    """Phone is a required field for patients — see data/models/patient.py docstring."""
    cleaned = (phone or "").strip()
    if not cleaned:
        raise ValidationError(t("validation.phone_required"))
    if not _PHONE_ALLOWED_CHARS_RE.match(cleaned):
        raise ValidationError(t("validation.phone_invalid_chars"))
    digit_count = sum(ch.isdigit() for ch in cleaned)
    if not (_PHONE_DIGITS_MIN <= digit_count <= _PHONE_DIGITS_MAX):
        raise ValidationError(
            t(
                "validation.phone_digit_count",
                min_digits=_PHONE_DIGITS_MIN,
                max_digits=_PHONE_DIGITS_MAX,
            )
        )
    return cleaned


def validate_email(email: str | None) -> str | None:
    """Email is optional for patients — None/empty is valid. See patient.py docstring."""
    if email is None:
        return None
    cleaned = email.strip()
    if not cleaned:
        return None
    if len(cleaned) > 150:
        raise ValidationError(t("validation.email_too_long"))
    if not _EMAIL_RE.match(cleaned):
        raise ValidationError(t("validation.email_invalid"))
    return cleaned


def _to_decimal(value, field_key: str) -> Decimal:
    """
    Coerce input to Decimal without ever routing through float — the
    "Decimal throughout" rule (design doc Section 3 / task plan 2.2)
    means a caller passing a Python float here is itself a bug we want
    to surface, not silently accept, since float -> Decimal conversion
    can bake in binary-rounding error before we ever see the value.
    NaN / Infinity parse as Decimals but are never valid amounts.
    """
    field_name = t(field_key)
    if isinstance(value, float):
        raise ValidationError(t("validation.not_a_decimal", field=field_name))
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(t("validation.not_a_number", field=field_name)) from exc
    if not result.is_finite():
        raise ValidationError(t("validation.not_a_number", field=field_name))
    return result


def validate_amount(value, field_key: str = "fields.total_amount") -> Decimal:
    """A monetary amount: Decimal, > 0, at most 2 decimal places (matches Numeric(12, 2))."""
    amount = _to_decimal(value, field_key)
    field_name = t(field_key)
    if amount <= 0:
        raise ValidationError(t("validation.amount_not_positive", field=field_name))
    if -amount.as_tuple().exponent > 2:
        raise ValidationError(t("validation.too_many_decimals", field=field_name))
    return amount


def validate_percentage(value, field_key: str = "fields.standard_percentage") -> Decimal:
    """A split percentage: Decimal, 0-100 inclusive, at most 2 decimal places (matches Numeric(5, 2))."""
    pct = _to_decimal(value, field_key)
    field_name = t(field_key)
    if pct < 0 or pct > 100:
        raise ValidationError(t("validation.percentage_out_of_range", field=field_name))
    if -pct.as_tuple().exponent > 2:
        raise ValidationError(t("validation.too_many_decimals", field=field_name))
    return pct

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


def validate_password(password: str | None) -> str:
    """
    Password policy for new/changed passwords. Deliberately NOT stripped —
    whitespace is a legitimate part of a password. Min length matches
    scripts/create_first_admin.py. Never echoes the password in the error.
    """
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(t("validation.password_too_short", min_length=PASSWORD_MIN_LENGTH))
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationError(t("validation.password_too_long", max_length=PASSWORD_MAX_LENGTH))
    return password

def validate_role(role: str | None) -> str:
    """Role must be one of the two confirmed roles (design doc Section 5.2 / 9)."""
    from data.models.user import VALID_ROLES

    if role not in VALID_ROLES:
        raise ValidationError(t("validation.role_invalid", roles=", ".join(VALID_ROLES)))
    return role


def validate_signed_amount(value, field_key: str = "fields.adjustment_amount") -> Decimal:
    """A signed monetary change: Decimal, never zero, at most 2 decimal places."""
    amount = _to_decimal(value, field_key)
    field_name = t(field_key)
    if amount == 0:
        raise ValidationError(t("validation.amount_zero", field=field_name))
    if -amount.as_tuple().exponent > 2:
        raise ValidationError(t("validation.too_many_decimals", field=field_name))
    return amount   