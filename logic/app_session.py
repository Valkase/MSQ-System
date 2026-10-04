"""
Session handling (task plan Phase 3: "how the GUI remembers who's logged
in during a session").

This is a single desktop app per front-desk PC (design doc Section 3), so
"the logged-in user" is process-wide state, the same way i18n's locale is.
Only the user's ID and a last-activity timestamp are held here — never the
User object or password — and get_user() re-fetches the row every time. So
if an admin deactivates an account, that user's very next action fails
instead of surviving until they log out.

Idle timeout: if no GUI action calls get_user() for IDLE_TIMEOUT, the
session ends and the user must log in again (front desks are shared,
unattended screens are a real risk). Set to None to disable. The GUI
should route every user action through get_user(), which counts as activity.

Named app_session (not session) to avoid confusion with SQLAlchemy sessions.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from data.models.user import User
from i18n import t
from logic.errors import AuthenticationError

DEFAULT_IDLE_TIMEOUT: timedelta | None = timedelta(minutes=30)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppSession:
    def __init__(self, idle_timeout: timedelta | None = DEFAULT_IDLE_TIMEOUT) -> None:
        self.idle_timeout = idle_timeout
        self._user_id: uuid.UUID | None = None
        self._last_activity: datetime | None = None

    def start(self, user: User, *, now: datetime | None = None) -> None:
        """Begin a session for `user` (called by logic.auth.login)."""
        self._user_id = user.id
        self._last_activity = now or utcnow()

    def end(self) -> None:
        """Log out. Safe to call when nobody is logged in."""
        self._user_id = None
        self._last_activity = None

    def _is_idle_expired(self, now: datetime) -> bool:
        if self.idle_timeout is None or self._last_activity is None:
            return False
        return now - self._last_activity > self.idle_timeout

    def is_logged_in(self, *, now: datetime | None = None) -> bool:
        """Cheap check for the GUI (no DB). Does not count as activity."""
        if self._user_id is None:
            return False
        return not self._is_idle_expired(now or utcnow())

    @property
    def user_id(self) -> uuid.UUID | None:
        return self._user_id

    def get_user(self, db_session: Session, *, now: datetime | None = None) -> User:
        """
        The current User, freshly loaded. Use this as `acting_user` for
        logic-layer calls. Raises AuthenticationError (and ends the
        session) if nobody is logged in, the session idled out, or the
        account was deactivated/deleted since login. Counts as activity.
        """
        now = now or utcnow()
        if self._user_id is None:
            raise AuthenticationError(t("auth.not_logged_in"))
        if self._is_idle_expired(now):
            self.end()
            raise AuthenticationError(t("auth.session_expired"))

        user = db_session.get(User, self._user_id)
        if user is None or not user.active:
            self.end()
            raise AuthenticationError(t("auth.account_deactivated"))

        self._last_activity = now
        return user


# The process-wide session the GUI uses.
current_session = AppSession()