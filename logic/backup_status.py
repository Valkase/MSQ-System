"""
Backup health for the admin warning (task plan Phase 7: "alerts, e.g. on next
admin login, if the drive isn't present when a backup was due").

Judged from the age of the last SUCCESSFUL backup, not from what the job
reports, so it still warns when the scheduled task was disabled or never ran.
Admin-only (VIEW_BACKUP_STATUS).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backup import settings as backup_settings
from backup.storage import as_aware_utc
from data.models.backup_run import STATUS_OK, BackupRun
from data.models.user import User
from logic.permissions import Permission, require_permission

STATE_OK = "ok"
STATE_NEVER = "never"
STATE_OVERDUE = "overdue"


@dataclass(frozen=True)
class BackupHealth:
    state: str
    last_success_at: datetime | None
    last_attempt_status: str | None
    last_attempt_at: datetime | None


def get_backup_health(
    session: Session,
    *,
    acting_user: User,
    now: datetime | None = None,
    alert_after: timedelta | None = None,
) -> BackupHealth:
    require_permission(acting_user, Permission.VIEW_BACKUP_STATUS)

    now = now or datetime.now(timezone.utc)
    alert_after = alert_after or backup_settings.alert_after()

    last_ok = (
        session.query(func.max(BackupRun.started_at)).filter(BackupRun.status == STATUS_OK).scalar()
    )
    last = session.query(BackupRun).order_by(BackupRun.started_at.desc()).first()

    last_success = as_aware_utc(last_ok) if last_ok else None
    attempt_status = last.status if last else None
    attempt_at = as_aware_utc(last.started_at) if last else None

    if last_success is None:
        state = STATE_NEVER
    elif now - last_success > alert_after:
        state = STATE_OVERDUE
    else:
        state = STATE_OK
    return BackupHealth(state, last_success, attempt_status, attempt_at)