"""
Application controller: owns the QApplication, the active top-level
window, and the app-wide language. Screens never create each other
directly — they ask the controller (show_login / show_main /
change_language), so swapping screens and rebuilding after a language
change happen in exactly one place.
"""

import logging
import sys

from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtWidgets import QApplication

from gui.login_screen import LoginScreen
from gui.main_window import MainWindow
from i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, get_locale, set_locale
from logic import auth
from logic.app_session import current_session
from logic.errors import AuthenticationError

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