"""
Shared date-range helper for the financial logic and reporting modules
(task plan 2.2's "arbitrary custom date range" requirement, e.g.
15 Nov-23 Dec). Kept in its own module, rather than private to
transactions.py, since both logic/transactions.py and logic/reports.py
need to agree on exactly what "15 Nov to 23 Dec" means.

A "day" here is the PC's LOCAL calendar day, matching what the GUI shows
(timestamps are stored in UTC but displayed in local time). The bounds are
converted to UTC for comparing against Transaction.created_at.
"""

from datetime import date, datetime, time, timezone

from i18n import t
from logic.errors import ValidationError


def day_bounds_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """
    Turn an inclusive [start_date, end_date] calendar-day range into the
    UTC datetime bounds used to filter Transaction.created_at (stored
    timezone-aware): start_date 00:00:00 local through end_date
    23:59:59.999999 local, inclusive on both ends, converted to UTC.
    """
    if end_date < start_date:
        raise ValidationError(t("dates.end_before_start"))
    # A naive datetime is interpreted as the machine's local time by astimezone().
    start_dt = datetime.combine(start_date, time.min).astimezone(timezone.utc)
    end_dt = datetime.combine(end_date, time.max).astimezone(timezone.utc)
    return start_dt, end_dt