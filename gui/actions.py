"""
Shared helpers for GUI screens: message boxes and run_logic(), the one
way a screen talks to the logic layer.

    ok, result = run_logic(self, self.controller, lambda db, user: ...)
    if not ok:
        return

run_logic opens a fresh DB session, calls current_session.get_user(db) (so
idle timeout / deactivation are enforced on EVERY action), and runs your
function with (db, user). The function must return plain data, not ORM
objects: they're detached when the session closes. On failure it shows a
message and returns (False, None). If the session is no longer valid it
sends the user back to the login screen; after that, the caller must not
touch its widgets (just return).
"""

import logging

from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy.exc import OperationalError

from gui.db import db_session
from i18n import t
from logic.app_session import current_session
from logic.errors import AuthenticationError, LogicError

log = logging.getLogger(__name__)


def show_message(parent, text: str, icon=QMessageBox.Icon.Warning) -> None:
    box = QMessageBox(icon, t("gui.app_title"), text, QMessageBox.StandardButton.NoButton, parent)
    box.addButton(t("gui.ok"), QMessageBox.ButtonRole.AcceptRole)
    box.exec()


def confirm(parent, text: str) -> bool:
    """Yes/No question with translated buttons; defaults to No."""
    box = QMessageBox(
        QMessageBox.Icon.Question, t("gui.app_title"), text, QMessageBox.StandardButton.NoButton, parent
    )
    yes = box.addButton(t("gui.yes"), QMessageBox.ButtonRole.YesRole)
    no = box.addButton(t("gui.no"), QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes


def run_logic(parent, controller, func):
    try:
        with db_session() as db:
            user = current_session.get_user(db)
            return True, func(db, user)
    except AuthenticationError as exc:  # also covers AccountLockedError
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.reject()  # don't leave a dialog open over the login screen
        controller.show_login(str(exc))
        return False, None
    except LogicError as exc:  # validation, permission, not-found, ...
        show_message(parent, str(exc))
        return False, None
    except OperationalError:
        log.exception("Database unreachable")
        show_message(parent, t("gui.error.db_unavailable"), QMessageBox.Icon.Critical)
        return False, None
    except Exception:
        log.exception("Unexpected error in GUI action")
        show_message(parent, t("gui.error.unexpected"), QMessageBox.Icon.Critical)
        return False, None