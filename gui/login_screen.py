"""Login screen (task plan Phase 4, first item)."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from gui.db import db_session
from gui.widgets import LanguageSwitcher
from i18n import t
from logic import auth
from logic.errors import AccountLockedError, AuthenticationError

log = logging.getLogger(__name__)


class LoginScreen(QWidget):
    def __init__(self, controller, message: str | None = None):
        super().__init__()
        self.controller = controller
        self.setWindowTitle(t("gui.app_title"))
        self.setMinimumWidth(380)

        title = QLabel(t("gui.app_title"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)

        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout()
        form.addRow(t("fields.username"), self.username)
        form.addRow(t("fields.password"), self.password)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setVisible(False)

        self.button = QPushButton(t("gui.login.button"))
        self.button.setDefault(True)
        self.button.clicked.connect(self._attempt_login)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._attempt_login)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 24)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.button)
        layout.addStretch()
        layout.addWidget(LanguageSwitcher(controller))

        if message:
            self._show_error(message)
        self.username.setFocus()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(True)

    def _fail(self, text: str) -> None:
        self._show_error(text)
        self.password.clear()  # never leave a rejected password in the box
        self.button.setEnabled(True)
        self.password.setFocus()

    def _attempt_login(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self._show_error(t("gui.login.fields_required"))
            return

        self.button.setEnabled(False)
        try:
            with db_session() as db:
                auth.login(db, username=username, password=password)
        except AccountLockedError as exc:  # subclass: must be caught before AuthenticationError
            self._fail(str(exc))
            return
        except AuthenticationError as exc:
            self._fail(str(exc))
            return
        except OperationalError:
            log.exception("Database unreachable during login")
            self._fail(t("gui.error.db_unavailable"))
            return
        except Exception:
            log.exception("Unexpected error during login")  # never log the password
            self._fail(t("gui.error.unexpected"))
            return

        self.controller.show_main()