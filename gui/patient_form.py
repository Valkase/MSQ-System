"""New / edit patient dialog (shared). Stays open if the save fails."""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
)

from i18n import t


class PatientFormDialog(QDialog):
    """
    `save(values, parent)` is called on Save and returns True on success.
    `parent` is this dialog, so any message box it shows appears on top of
    the (modal) dialog instead of behind it. If it returns False the
    dialog stays open with the user's input intact.
    `initial` (optional) uses the same keys as values().
    """

    def __init__(self, parent, *, title: str, save, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self._save = save
        initial = initial or {}

        self.full_name = QLineEdit(initial.get("full_name") or "")
        self.phone = QLineEdit(initial.get("phone") or "")
        self.email = QLineEdit(initial.get("email") or "")
        self.address = QLineEdit(initial.get("address") or "")

        self.dob_known = QCheckBox(t("gui.patients.dob_known"))
        self.dob = QDateEdit()
        self.dob.setCalendarPopup(True)
        self.dob.setDisplayFormat("yyyy-MM-dd")
        self.dob.setMinimumDate(QDate(1900, 1, 1))
        self.dob.setMaximumDate(QDate.currentDate())
        existing = initial.get("date_of_birth")
        if existing:
            self.dob.setDate(QDate(existing.year, existing.month, existing.day))
            self.dob_known.setChecked(True)
        self.dob.setEnabled(self.dob_known.isChecked())
        self.dob_known.toggled.connect(self.dob.setEnabled)

        dob_row = QHBoxLayout()
        dob_row.addWidget(self.dob_known)
        dob_row.addWidget(self.dob, 1)

        form = QFormLayout()
        form.addRow(t("fields.full_name"), self.full_name)
        form.addRow(t("fields.phone"), self.phone)
        form.addRow(t("fields.email"), self.email)
        form.addRow(t("fields.date_of_birth"), dob_row)
        form.addRow(t("fields.address"), self.address)

        buttons = QDialogButtonBox()
        self._save_button = buttons.addButton(t("gui.save"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(t("gui.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self._save_button.setDefault(True)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.full_name.setFocus()

    def values(self) -> dict:
        return {
            "full_name": self.full_name.text(),
            "phone": self.phone.text(),
            "email": self.email.text(),
            "date_of_birth": self.dob.date().toPython() if self.dob_known.isChecked() else None,
            "address": self.address.text(),
        }

    def _on_save(self) -> None:
        self._save_button.setEnabled(False)  # no double-submit while saving
        try:
            if self._save(self.values(), self):
                self.accept()
        finally:
            self._save_button.setEnabled(True)