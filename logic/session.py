"""
Session handling (task plan Phase 3, third item): "how the GUI remembers
who's logged in during a session".

Design: a single process-wide "current user" slot, not a token or a
per-call argument threaded through every GUI event handler. This mirrors
i18n/translator.py's get_locale()/set_locale() pattern exactly, and for
the same reason (see that module's docstring): this is a single desktop
app installed per front-desk PC (design doc Section 3), with one
receptionist logged in at a time on that machine. There's no server, no
concurrent requests from different users inside one process, and no
need for anything resembling a web session token — "who's logged in
right now" is simply a fact about this running process.

Usage from the GUI layer:

    from logic.session import start_session, end_session, current_user, is_logged_in

    user = login(db_session, username=..., password=...)   # logic/auth.py
    start_session(user)
    ...
    acting_user = current_user()   # pass into any logic-layer call
    ...
    end_session()   # on logout

Logic-layer functions still take `acting_user` explicitly (see
logic/patients.py, logic/doctors.py, etc.) rather than reaching into this
module themselves — this keeps every logic function testable in
isolation with an arbitrary user, the same way tests/conftest.py's
`admin_user`/`receptionist_user` fixtures already work, with no session
state to set up or tear down per test. This module is purely a
convenience for the GUI layer to avoid manually passing the logged-in
user through every screen and event handler.
"""

from data.models.user import User
from logic.errors import LogicError


class NoActiveSessionError(LogicError):
    """Raised by current_user() when nothing is logged in — a GUI screen
    tried to act on behalf of a user before start_session() was called
    (or after end_session()/a timeout logged them out)."""


_current_user: User | None = None


def start_session(user: User) -> None:
    """
    Mark `user` as the logged-in user for this process. Called by the
    GUI right after logic.auth.login() succeeds — this module doesn't
    verify credentials itself, it only remembers the result.

    Deliberately does NOT re-check user.active here: logic.auth.login()
    already refuses to return a deactivated user, so by the time this is
    called the user is known-valid. If a currently-active session's user
    is deactivated *while* they're logged in (an admin deactivates them
    mid-session from another desk), that's each individual logic-layer
    call's require_permission() check that catches it on the next
    action, not this module's job.
    """
    global _current_user
    _current_user = user


def end_session() -> None:
    """Clear the logged-in user — called on logout, or before showing the login screen again."""
    global _current_user
    _current_user = None


def current_user() -> User:
    """
    The currently logged-in user. Raises NoActiveSessionError if nobody
    is logged in, rather than returning None — every call site that
    needs `acting_user` should be somewhere only reachable after login,
    so silently returning None would just turn into a confusing
    AttributeError two lines later instead of a clear error here.
    """
    if _current_user is None:
        raise NoActiveSessionError(
            "No user is currently logged in — start_session() must be called after a "
            "successful login() before any action requiring acting_user."
        )
    return _current_user


def is_logged_in() -> bool:
    """Non-raising check — for the GUI to decide whether to show the login screen or the main window."""
    return _current_user is not None