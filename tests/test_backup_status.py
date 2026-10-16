"""Admin backup warning logic (logic/backup_status.py)."""

from datetime import datetime, timedelta, timezone

import pytest

from data.models.backup_run import BackupRun
from logic import backup_status
from logic.errors import PermissionDeniedError

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
LIMIT = timedelta(hours=30)


def add(session, status, hours_ago, **kw):
    when = NOW - timedelta(hours=hours_ago)
    session.add(BackupRun(started_at=when, finished_at=when, status=status, **kw))
    session.commit()


def health(session, user):
    return backup_status.get_backup_health(session, acting_user=user, now=NOW, alert_after=LIMIT)


def test_never_backed_up(session, admin_user):
    result = health(session, admin_user)
    assert result.state == backup_status.STATE_NEVER
    assert result.last_success_at is None and result.last_attempt_status is None


def test_recent_success_is_ok(session, admin_user):
    add(session, "ok", 13, drive_id="d1")
    assert health(session, admin_user).state == backup_status.STATE_OK


def test_old_success_is_overdue_and_reports_the_latest_attempt(session, admin_user):
    add(session, "ok", 40, drive_id="d1")
    add(session, "drive_missing", 2)

    result = health(session, admin_user)

    assert result.state == backup_status.STATE_OVERDUE
    assert result.last_attempt_status == "drive_missing"
    assert result.last_success_at == NOW - timedelta(hours=40)


def test_a_failed_attempt_after_a_recent_success_is_not_an_alarm(session, admin_user):
    add(session, "ok", 13, drive_id="d1")
    add(session, "failed", 2, error="one drive failed")  # the other drive succeeded
    assert health(session, admin_user).state == backup_status.STATE_OK


def test_never_with_only_failed_attempts(session, admin_user):
    add(session, "drive_missing", 5)
    result = health(session, admin_user)
    assert result.state == backup_status.STATE_NEVER
    assert result.last_attempt_status == "drive_missing"


def test_receptionists_cannot_view_backup_status(session, receptionist_user):
    with pytest.raises(PermissionDeniedError):
        health(session, receptionist_user)