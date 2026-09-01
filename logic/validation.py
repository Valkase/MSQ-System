"""
Shared field-level validation helpers.

Kept deliberately separate from the models (which just store data) and
from any single entity's logic module, since phone/email/name-shaped
fields are reused across patients, doctors, and users. Every validator
either returns a cleaned value or raises logic.errors.ValidationError —
they never touch the database.

NOTE on localization (task plan 2.5): the *messages* raised here are
English placeholders. Once locales/en and locales/ar are wired up, these
should raise with message *keys* (e.g. "error.phone_invalid") instead of
literal English text, so the GUI layer can translate them. Left as
plain English for now since localization wiring is a separate task.
"""

import re
from decimal import Decimal, InvalidOperation

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


def validate_required_text(value: str | None, field_name: str, *, max_length: int) -> str:
    """Strip, require non-empty, and enforce a max length. Returns the cleaned value."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValidationError(f"{field_name} is required.")
    if len(cleaned) > max_length:
        raise ValidationError(f"{field_name} must be {max_length} characters or fewer.")
    return cleaned


def validate_optional_text(value: str | None, field_name: str, *, max_length: int) -> str | None:
    """Same as validate_required_text but allows None/empty (returns None in that case)."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValidationError(f"{field_name} must be {max_length} characters or fewer.")
    return cleaned


def validate_phone(phone: str | None) -> str:
    """Phone is a required field for patients — see data/models/patient.py docstring."""
    cleaned = (phone or "").strip()
    if not cleaned:
        raise ValidationError("Phone number is required.")
    if not _PHONE_ALLOWED_CHARS_RE.match(cleaned):
        raise ValidationError("Phone number may only contain digits, spaces, '+' and '-'.")
    digit_count = sum(ch.isdigit() for ch in cleaned)
    if not (_PHONE_DIGITS_MIN <= digit_count <= _PHONE_DIGITS_MAX):
        raise ValidationError(
            f"Phone number must contain between {_PHONE_DIGITS_MIN} and "
            f"{_PHONE_DIGITS_MAX} digits."
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
        raise ValidationError("Email must be 150 characters or fewer.")
    if not _EMAIL_RE.match(cleaned):
        raise ValidationError("Email address is not a valid format.")
    return cleaned


def _to_decimal(value, field_name: str) -> Decimal:
    """
    Coerce input to Decimal without ever routing through float — the
    "Decimal throughout" rule (design doc Section 3 / task plan 2.2)
    means a caller passing a Python float here is itself a bug we want
    to surface, not silently accept, since float -> Decimal conversion
    can bake in binary-rounding error before we ever see the value.
    """
    if isinstance(value, float):
        raise ValidationError(
            f"{field_name} must be a Decimal (or int/str), not a float — "
            "floats can introduce rounding error before validation ever sees the value."
        )
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} is not a valid number.") from exc


def validate_amount(value, field_name: str = "Amount") -> Decimal:
    """A monetary amount: Decimal, > 0, at most 2 decimal places (matches Numeric(12, 2))."""
    amount = _to_decimal(value, field_name)
    if amount <= 0:
        raise ValidationError(f"{field_name} must be greater than zero.")
    if -amount.as_tuple().exponent > 2:
        raise ValidationError(f"{field_name} may have at most 2 decimal places.")
    return amount


def validate_percentage(value, field_name: str = "Percentage") -> Decimal:
    """A split percentage: Decimal, 0–100 inclusive, at most 2 decimal places (matches Numeric(5, 2))."""
    pct = _to_decimal(value, field_name)
    if pct < 0 or pct > 100:
        raise ValidationError(f"{field_name} must be between 0 and 100.")
    if -pct.as_tuple().exponent > 2:
        raise ValidationError(f"{field_name} may have at most 2 decimal places.")
    return pct