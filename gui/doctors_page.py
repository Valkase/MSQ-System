"""Doctors administration screen (task plan Phase 4, admin-only): add, edit name/rate, deactivate."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.actions import confirm, run_logic, show_message
from i18n import format_number, t
from logic import doctors
from gui.edit_history_view import show_history


class DoctorFormDialog(QDialog):
    """
    `save(values, parent)` returns True on success. values = {"name": str,
    "percentage": str}. The percentage is passed as text; the logic layer
    parses it as a Decimal (never a float).
    """

    def __init__(self, parent, *, title: str, save, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self._save = save
        initial = initial or {}

        self.name = QLineEdit(initial.get("name") or "")
        self.percentage = QLineEdit(str(initial["percentage"]) if "percentage" in initial else "")
        self.percentage.setPlaceholderText("60.00")

        note = QLabel(t("gui.doctors.rate_note"))
        note.setWordWrap(True)

        form = QFormLayout()
        form.addRow(t("fields.doctor_name"), self.name)
        form.addRow(t("fields.standard_percentage"), self.percentage)

        buttons = QDialogButtonBox()
        self._save_button = buttons.addButton(t("gui.save"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(t("gui.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self._save_button.setDefault(True)
        self.history_button = QPushButton(t("gui.history.button"))
        self.history_button.clicked.connect(self._history)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.name.setFocus()


    def values(self) -> dict:
        return {"name": self.name.text(), "percentage": self.percentage.text().strip()}

    def _on_save(self) -> None:
        self._save_button.setEnabled(False)
        try:
            if self._save(self.values(), self):
                self.accept()
        finally:
            self._save_button.setEnabled(True)


class DoctorsPage(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._rows: list[dict] = []

        self.show_inactive = QCheckBox(t("gui.doctors.show_inactive"))
        new_button = QPushButton(t("gui.doctors.new"))
        new_button.clicked.connect(self._new)
        self.edit_button = QPushButton(t("gui.doctors.edit"))
        self.edit_button.clicked.connect(self._edit)
        self.toggle_button = QPushButton(t("gui.deactivate"))
        self.toggle_button.clicked.connect(self._toggle_active)

        top = QHBoxLayout()
        top.addWidget(new_button)
        top.addWidget(self.edit_button)
        top.addWidget(self.toggle_button)
        top.addWidget(self.history_button)
        top.addStretch()
        top.addWidget(self.show_inactive)
        
        

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [t("gui.doctors.col_name"), t("gui.doctors.col_percentage"), t("gui.doctors.col_status")]
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
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._edit())

        self.count_label = QLabel()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.count_label)

        self.show_inactive.toggled.connect(lambda _checked: self.refresh())

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    # --- data ------------------------------------------------------------------

    def refresh(self) -> None:
        include_inactive = self.show_inactive.isChecked()
        ok, rows = run_logic(
            self,
            self.controller,
            lambda db, user: [
                {"id": d.id, "name": d.name, "pct": d.standard_percentage, "active": d.active}
                for d in doctors.list_doctors(db, include_inactive=include_inactive)
            ],
        )
        if not ok:
            return
        self._rows = rows

        grey = QBrush(QColor("#888888"))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            status = t("gui.status.active") if row["active"] else t("gui.status.inactive")
            cells = [row["name"], f"{format_number(row['pct'])}%", status]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter)
                if not row["active"]:
                    item.setForeground(grey)
                self.table.setItem(r, c, item)
        self.count_label.setText(t("gui.doctors.count", count=len(rows)))
        self._on_selection()

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def _on_selection(self) -> None:
        doctor = self._selected()
        active = doctor["active"] if doctor else True
        self.toggle_button.setText(t("gui.deactivate") if active else t("gui.reactivate"))

    def _require_selection(self) -> dict | None:
        doctor = self._selected()
        if doctor is None:
            show_message(self, t("gui.doctors.select_first"))
        return doctor

    # --- actions ---------------------------------------------------------------

    def _new(self) -> None:
        def save(values: dict, parent) -> bool:
            ok, _ = run_logic(
                parent,
                self.controller,
                lambda db, user: doctors.create_doctor(
                    db,
                    name=values["name"],
                    standard_percentage=values["percentage"],
                    acting_user=user,
                ).id,
            )
            return ok

        dialog = DoctorFormDialog(self, title=t("gui.doctors.new_title"), save=save)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit(self) -> None:
        doctor = self._require_selection()
        if doctor is None:
            return
        doctor_id, original_name = doctor["id"], doctor["name"]

        def save(values: dict, parent) -> bool:
            def apply(db, user):
                # Each call validates, logs to audit_logs and commits on its own.
                # Re-running after a partial failure is safe: unchanged values are no-ops.
                if values["name"].strip() != original_name:
                    doctors.rename_doctor(
                        db, doctor_id=doctor_id, new_name=values["name"], acting_user=user
                    )
                doctors.update_doctor_percentage(
                    db,
                    doctor_id=doctor_id,
                    new_percentage=values["percentage"],
                    acting_user=user,
                )

            ok, _ = run_logic(parent, self.controller, apply)
            return ok

        dialog = DoctorFormDialog(
            self,
            title=t("gui.doctors.edit_title"),
            save=save,
            initial={"name": original_name, "percentage": doctor["pct"]},
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _toggle_active(self) -> None:
        doctor = self._require_selection()
        if doctor is None:
            return
        activate = not doctor["active"]
        key = "gui.doctors.confirm_reactivate" if activate else "gui.doctors.confirm_deactivate"
        if not confirm(self, t(key, name=doctor["name"])):
            return
        action = doctors.reactivate_doctor if activate else doctors.deactivate_doctor
        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: action(db, doctor_id=doctor["id"], acting_user=user),
        )
        if ok:
            self.refresh()


    def _history(self) -> None:
        doctor = self._require_selection()
        if doctor is None:
            return
        show_history(
            self,
            self.controller,
            table_name="doctors",
            record_id=doctor["id"],
            title=doctor["name"],
        )