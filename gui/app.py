"""
Application controller: owns the QApplication, the active top-level
window, and the app-wide language. Screens never create each other
directly — they ask the controller (show_login / show_main /
change_language / apply_update), so swapping screens and rebuilding after a
language change happen in exactly one place.
"""

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtWidgets import QApplication

from data.database import engine
from data.schema_check import SchemaStatus, check_schema
from gui.login_screen import LoginScreen
from gui.main_window import MainWindow
from i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, get_locale, set_locale
from logic import auth
from logic.app_session import current_session
from logic.errors import AuthenticationError
from updater.apply import UpdateApplyError, cleanup_stale_staging, start_update

log = logging.getLogger(__name__)


class _ActivityFilter(QObject):
    """Feeds real user input into the session's idle timer (no DB access)."""

    _EVENTS = {QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress}

    def eventFilter(self, obj, event):
        if event.type() in self._EVENTS:
            current_session.touch()
        return False  # never swallow the event


class AppController:
    def __init__(self, app: QApplication):
        self.app = app
        self.window = None
        self.settings = QSettings("HealthCenter", "HealthCenterSystem")
        self._activity_filter = _ActivityFilter()
        app.installEventFilter(self._activity_filter)
        app.aboutToQuit.connect(auth.logout)

        saved = str(self.settings.value("locale", DEFAULT_LOCALE))
        self._apply_locale(saved)

        try:
            cleanup_stale_staging()  # leftovers from earlier update attempts
        except Exception:
            log.debug("Staging cleanup failed (ignored)", exc_info=True)

    # --- language -------------------------------------------------------------

    def _apply_locale(self, code: str) -> None:
        if code not in SUPPORTED_LOCALES:
            code = DEFAULT_LOCALE
        set_locale(code)
        self.app.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if code == "ar" else Qt.LayoutDirection.LeftToRight
        )

    def change_language(self, code: str) -> None:
        if code == get_locale():
            return
        self._apply_locale(code)
        self.settings.setValue("locale", code)
        # Rebuild the current screen so every string and the layout direction refresh.
        if isinstance(self.window, MainWindow):
            self.show_main(page=self.window.current_page())
        else:
            self.show_login()

    # --- schema / updates -----------------------------------------------------

    def schema_status(self) -> SchemaStatus | None:
        """
        Does the shared database match this build's schema? None when it can't
        be determined (e.g. database unreachable): the login attempt will then
        report the connection problem itself.
        """
        try:
            return check_schema(engine)
        except Exception:
            log.warning("Could not check the database schema", exc_info=True)
            return None

    def apply_update(self, staged_exe: Path) -> bool:
        """Hand a verified update to the helper and quit. False if it couldn't start."""
        try:
            start_update(staged_exe)
        except UpdateApplyError:
            log.exception("Could not start the updater")
            return False
        except Exception:
            log.exception("Unexpected error starting the updater")
            return False
        self.app.quit()  # aboutToQuit logs the user out; the helper waits for this process to end
        return True

    # --- screens --------------------------------------------------------------

    def _replace(self, new_window) -> None:
        old, self.window = self.window, new_window
        new_window.show()  # show the new one first so the app never has zero windows
        if old is not None:
            old.close()
            old.deleteLater()

    def show_login(self, message: str | None = None) -> None:
        auth.logout()
        self._replace(LoginScreen(self, message))

    def show_main(self, page: int = 0) -> None:
        try:
            window = MainWindow(self, start_page=page)
        except AuthenticationError as exc:
            self.show_login(str(exc))
            return
        self._replace(window)


def run() -> int:
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    controller = AppController(app)
    controller.show_login()
    return app.exec()
