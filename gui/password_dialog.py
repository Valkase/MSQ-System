"""Password dialog, shared by 'reset user password' (admin) and 'change my password'."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from gui.actions import show_message
from i18n import t


def password_field() -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


class PasswordDialog(QDialog):
    """
    `save(values, parent)` returns True on success (dialog closes) or False
    (dialog stays open). values = {"current": str | None, "new": str}.
    `current` is only asked for when ask_current=True (changing your own password).
    """

    def __init__(self, parent, *, title: str, save, ask_current: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self._save = save

        self.current = password_field() if ask_current else None
        self.new = password_field()
        self.confirm = password_field()

        form = QFormLayout()
        if self.current is not None:
            form.addRow(t("gui.users.current_password"), self.current)
        form.addRow(t("gui.users.new_password"), self.new)
        form.addRow(t("gui.users.password_confirm"), self.confirm)

        buttons = QDialogButtonBox()
        self._save_button = buttons.addButton(t("gui.save"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(t("gui.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self._save_button.setDefault(True)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        (self.current or self.new).setFocus()

    def values(self) -> dict:
        return {
            "current": self.current.text() if self.current is not None else None,
            "new": self.new.text(),
        }

    def _on_save(self) -> None:
        if self.new.text() != self.confirm.text():
            show_message(self, t("gui.users.password_mismatch"))
            return
        self._save_button.setEnabled(False)
        try:
            if self._save(self.values(), self):
                self.accept()
            elif self.current is not None:
                self.current.clear()  # never leave a rejected password sitting in the box
        finally:
            self._save_button.setEnabled(True)