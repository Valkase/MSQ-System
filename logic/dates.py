"""
Shared date-range helper for the financial logic and reporting modules
(task plan 2.2's "arbitrary custom date range" requirement, e.g.
15 Nov-23 Dec). Kept in its own module, rather than private to
transactions.py, since both logic/transactions.py and logic/reports.py
need to agree on exactly what "15 Nov to 23 Dec" means in UTC.
"""

from datetime import date, datetime, time, timezone

from i18n import t
from logic.errors import ValidationError


def day_bounds_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """
    Turn an inclusive [start_date, end_date] calendar-day range into the
    UTC datetime bounds used to filter Transaction.created_at (stored
    timezone-aware). start_date 00:00:00 UTC through end_date
    23:59:59.999999 UTC, inclusive on both ends.
    """
    if end_date < start_date:
        raise ValidationError(t("dates.end_before_start"))
    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    return start_dt, end_dt