"""Users administration screen (task plan Phase 4, admin-only): create, reset password, deactivate, unlock."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.models.user import ROLE_RECEPTIONIST, VALID_ROLES
from gui.actions import confirm, run_logic, show_message
from gui.password_dialog import PasswordDialog, password_field
from i18n import t
from logic import auth


class UserFormDialog(QDialog):
    """`save(values, parent)` returns True on success. values: username, password, role."""

    def __init__(self, parent, *, save):
        super().__init__(parent)
        self.setWindowTitle(t("gui.users.new_title"))
        self.setMinimumWidth(420)
        self._save = save

        self.username = QLineEdit()
        self.password = password_field()
        self.confirm = password_field()
        self.role = QComboBox()
        for role in VALID_ROLES:
            self.role.addItem(t(f"gui.role.{role}"), role)
        self.role.setCurrentIndex(self.role.findData(ROLE_RECEPTIONIST))

        form = QFormLayout()
        form.addRow(t("fields.username"), self.username)
        form.addRow(t("fields.password"), self.password)
        form.addRow(t("gui.users.password_confirm"), self.confirm)
        form.addRow(t("fields.role"), self.role)

        buttons = QDialogButtonBox()
        self._save_button = buttons.addButton(t("gui.save"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(t("gui.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self._save_button.setDefault(True)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.username.setFocus()

    def values(self) -> dict:
        return {
            "username": self.username.text(),
            "password": self.password.text(),
            "role": self.role.currentData(),
        }

    def _on_save(self) -> None:
        if self.password.text() != self.confirm.text():
            show_message(self, t("gui.users.password_mismatch"))
            return
        self._save_button.setEnabled(False)
        try:
            if self._save(self.values(), self):
                self.accept()
        finally:
            self._save_button.setEnabled(True)


class UsersPage(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._rows: list[dict] = []

        new_button = QPushButton(t("gui.users.new"))
        new_button.clicked.connect(self._new)
        reset_button = QPushButton(t("gui.users.reset_password"))
        reset_button.clicked.connect(self._reset_password)
        self.toggle_button = QPushButton(t("gui.deactivate"))
        self.toggle_button.clicked.connect(self._toggle_active)
        self.unlock_button = QPushButton(t("gui.users.unlock"))
        self.unlock_button.clicked.connect(self._unlock)

        top = QHBoxLayout()
        for button in (new_button, reset_button, self.toggle_button, self.unlock_button):
            top.addWidget(button)
        top.addStretch()

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [t("gui.users.col_username"), t("gui.users.col_role"), t("gui.users.col_status")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection)

        self.count_label = QLabel()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.count_label)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()  # lockouts/deactivations may have changed since last shown

    # --- data ------------------------------------------------------------------

    def refresh(self) -> None:
        def fetch(db, user):
            now = datetime.now(timezone.utc)
            rows = []
            for u in auth.list_users(db, acting_user=user):
                locked_until = u.locked_until
                if locked_until is not None and locked_until.tzinfo is None:
                    locked_until = locked_until.replace(tzinfo=timezone.utc)
                rows.append(
                    {
                        "id": u.id,
                        "username": u.username,
                        "role": u.role,
                        "active": u.active,
                        "locked": locked_until is not None and locked_until > now,
                    }
                )
            return rows

        ok, rows = run_logic(self, self.controller, fetch)
        if not ok:
            return
        self._rows = rows

        grey = QBrush(QColor("#888888"))
        red = QBrush(QColor("#b00020"))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if not row["active"]:
                status, brush = t("gui.status.inactive"), grey
            elif row["locked"]:
                status, brush = t("gui.status.locked"), red
            else:
                status, brush = t("gui.status.active"), None
            for c, text in enumerate((row["username"], t(f"gui.role.{row['role']}"), status)):
                item = QTableWidgetItem(text)
                if brush is not None:
                    item.setForeground(brush)
                self.table.setItem(r, c, item)
        self.count_label.setText(t("gui.users.count", count=len(rows)))
        self._on_selection()

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _on_selection(self) -> None:
        user = self._selected()
        self.toggle_button.setText(
            t("gui.deactivate") if (user is None or user["active"]) else t("gui.reactivate")
        )
        self.unlock_button.setEnabled(bool(user and user["locked"]))

    def _require_selection(self) -> dict | None:
        user = self._selected()
        if user is None:
            show_message(self, t("gui.users.select_first"))
        return user

    # --- actions ---------------------------------------------------------------

    def _new(self) -> None:
        def save(values: dict, parent) -> bool:
            ok, _ = run_logic(
                parent,
                self.controller,
                lambda db, user: auth.create_user(
                    db,
                    username=values["username"],
                    password=values["password"],
                    role=values["role"],
                    acting_user=user,
                ).id,
            )
            return ok

        dialog = UserFormDialog(self, save=save)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _reset_password(self) -> None:
        target = self._require_selection()
        if target is None:
            return

        def save(values: dict, parent) -> bool:
            def apply(db, user):
                auth.reset_user_password(
                    db, user_id=target["id"], new_password=values["new"], acting_user=user
                )
                return True

            ok, _ = run_logic(parent, self.controller, apply)
            return ok

        dialog = PasswordDialog(
            self, title=t("gui.users.reset_title", name=target["username"]), save=save
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            show_message(
                self,
                t("gui.users.password_reset_done", name=target["username"]),
                QMessageBox.Icon.Information,
            )
            self.refresh()  # a reset also clears any lockout

    def _toggle_active(self) -> None:
        target = self._require_selection()
        if target is None:
            return
        activate = not target["active"]
        key = "gui.users.confirm_reactivate" if activate else "gui.users.confirm_deactivate"
        if not confirm(self, t(key, name=target["username"])):
            return
        action = auth.reactivate_user if activate else auth.deactivate_user
        # Deactivating yourself is rejected by the logic layer and shown as a message.
        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: action(db, user_id=target["id"], acting_user=user),
        )
        if ok:
            self.refresh()

    def _unlock(self) -> None:
        target = self._require_selection()
        if target is None:
            return
        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: auth.unlock_user(db, user_id=target["id"], acting_user=user),
        )
        if ok:
            self.refresh()