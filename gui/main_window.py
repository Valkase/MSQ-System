"""
Main window shell (task plan Phase 4): header (user, language, logout),
permission-filtered navigation, and a stacked area for the feature views.
Each PlaceholderPage below is swapped for a real view as it's built.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.db import db_session
from gui.widgets import LanguageSwitcher
from i18n import t
from logic.app_session import current_session
from logic.permissions import Permission, has_permission
from gui.patients_page import PatientsPage
from gui.transactions_page import TransactionsPage

# (message key for the label, permission needed to see it — None = everyone logged in)
_NAV = [
    ("gui.nav.patients", None),
    ("gui.nav.transactions", Permission.RECORD_TRANSACTION),
    ("gui.nav.reports", Permission.VIEW_REPORTS),
    ("gui.nav.doctors", Permission.MANAGE_DOCTORS),
    ("gui.nav.users", Permission.MANAGE_USERS),
]

IDLE_CHECK_INTERVAL_MS = 15_000


class PlaceholderPage(QWidget):
    def __init__(self, title: str):
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QLabel(title)
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        note = QLabel(t("gui.placeholder"))
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, controller, start_page: int = 0):
        super().__init__()
        self.controller = controller

        # Raises AuthenticationError if there's no valid session; the
        # controller handles that by returning to the login screen.
        with db_session() as db:
            user = current_session.get_user(db)
            username, role = user.username, user.role
            allowed = {p for p in Permission if has_permission(user, p)}

        self.setWindowTitle(t("gui.app_title"))
        self.resize(1100, 700)

        header = QHBoxLayout()
        header.addWidget(QLabel(f"{username} — {t('gui.role.' + role)}"))
        header.addStretch()
        header.addWidget(LanguageSwitcher(controller))
        logout_button = QPushButton(t("gui.logout"))
        logout_button.clicked.connect(lambda: controller.show_login())
        header.addWidget(logout_button)

        self.nav = QListWidget()
        self.nav.setFixedWidth(200)
        self.pages = QStackedWidget()
        for key, permission in _NAV:
            if permission is not None and permission not in allowed:
                continue
            self.nav.addItem(t(key))
            self.pages.addWidget(self._build_page(key))
       
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(max(0, min(start_page, self.nav.count() - 1)))

        body = QHBoxLayout()
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.addLayout(header)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)

        # Idle timeout: the controller's activity filter keeps the session
        # fresh on clicks/keys; this just notices when it has lapsed.
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start(IDLE_CHECK_INTERVAL_MS)

    def current_page(self) -> int:
        return self.nav.currentRow()

    def _build_page(self, key: str) -> QWidget:
        if key == "gui.nav.patients":
            return PatientsPage(self.controller)
        if key == "gui.nav.transactions":
            return TransactionsPage(self.controller)
        return PlaceholderPage(t(key))  # swapped out as each screen is built

    def _check_idle(self) -> None:
        if not current_session.is_logged_in():
            self.controller.show_login(t("auth.session_expired"))