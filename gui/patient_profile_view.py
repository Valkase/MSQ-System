"""
Patient profile view (task plan Phase 4): details, edit, deactivate /
reactivate, delete (falls back to deactivation when transactions exist),
attachments, billing history, and (admin-only) edit history.
"""

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.actions import confirm, run_logic, show_message
from gui.edit_history_view import show_history
from gui.patient_form import PatientFormDialog
from gui.transaction_table import TransactionTable
from i18n import format_date, t
from logic import attachments, patients, transactions
from logic.errors import PatientHasTransactionsError
from logic.permissions import Permission, has_permission


class PatientProfileView(QWidget):
    back_requested = Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._patient_id = None
        self._patient: dict | None = None

        back = QPushButton(t("gui.back"))
        back.clicked.connect(self.back_requested.emit)
        self.name_label = QLabel()
        font = self.name_label.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        self.name_label.setFont(font)
        header = QHBoxLayout()
        header.addWidget(back)
        header.addWidget(self.name_label, 1)

        self._fields = {key: QLabel() for key in
                        ("phone", "email", "date_of_birth", "address", "status")}
        form = QFormLayout()
        form.addRow(t("fields.phone"), self._fields["phone"])
        form.addRow(t("fields.email"), self._fields["email"])
        form.addRow(t("fields.date_of_birth"), self._fields["date_of_birth"])
        form.addRow(t("fields.address"), self._fields["address"])
        form.addRow(t("gui.patients.col_status"), self._fields["status"])
        for label in self._fields.values():
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)

        self.edit_button = QPushButton(t("gui.edit"))
        self.edit_button.clicked.connect(self._edit)
        self.toggle_button = QPushButton()
        self.toggle_button.clicked.connect(self._toggle_active)
        self.history_button = QPushButton(t("gui.history.button"))
        self.history_button.clicked.connect(self._history)
        self.delete_button = QPushButton(t("gui.patients.delete"))
        self.delete_button.clicked.connect(self._delete)
        actions = QHBoxLayout()
        actions.addWidget(self.edit_button)
        actions.addWidget(self.toggle_button)
        actions.addWidget(self.history_button)
        actions.addStretch()
        actions.addWidget(self.delete_button)

        self.attach_list = QListWidget()
        self.attach_list.itemDoubleClicked.connect(lambda _item: self._open_attachment())
        self.empty_label = QLabel(t("gui.attachments.empty"))
        self.attach_button = QPushButton(t("gui.attachments.attach"))
        self.attach_button.clicked.connect(self._attach)
        open_button = QPushButton(t("gui.attachments.open"))
        open_button.clicked.connect(self._open_attachment)
        attach_row = QHBoxLayout()
        attach_row.addWidget(self.attach_button)
        attach_row.addWidget(open_button)
        attach_row.addStretch()
        box = QGroupBox(t("gui.attachments.title"))
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(self.empty_label)
        box_layout.addWidget(self.attach_list)
        box_layout.addLayout(attach_row)

        self.history_table = TransactionTable(show_patient=False)
        self.history_empty = QLabel(t("gui.transactions.history_empty"))
        history_box = QGroupBox(t("gui.transactions.history_title"))
        history_layout = QVBoxLayout(history_box)
        history_layout.addWidget(self.history_empty)
        history_layout.addWidget(self.history_table)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(box, 1)
        layout.addWidget(history_box, 1)

    # --- loading ---------------------------------------------------------------

    def load(self, patient_id) -> bool:
        """Fetch and display a patient. Returns False if it couldn't be loaded."""

        def fetch(db, user):
            p = patients.get_patient(db, patient_id)
            atts = patients.list_attachments(db, patient_id)
            perms = {perm for perm in Permission if has_permission(user, perm)}
            history = (
                transactions.list_transaction_rows(
                    db, patient_id=patient_id, acting_user=user, limit=50
                )
                if Permission.VIEW_REPORTS in perms
                else []
            )
            return {
                "patient": {
                    "full_name": p.full_name,
                    "phone": p.phone,
                    "email": p.email,
                    "date_of_birth": p.date_of_birth,
                    "address": p.address,
                    "active": p.active,
                },
                "attachments": [
                    {"id": a.id, "file_path": a.file_path, "description": a.description}
                    for a in atts
                ],
                "perms": perms,
                "transactions": history,
            }

        ok, data = run_logic(self, self.controller, fetch)
        if not ok:
            return False
        self._patient_id = patient_id
        self._render(data)
        return True

    def _render(self, data: dict) -> None:
        p = data["patient"]
        perms = data["perms"]
        self._patient = p

        self.name_label.setText(p["full_name"])
        not_set = t("gui.patients.not_set")
        self._fields["phone"].setText(p["phone"])
        self._fields["email"].setText(p["email"] or not_set)
        dob = p["date_of_birth"]
        self._fields["date_of_birth"].setText(format_date(dob, format="long") if dob else not_set)
        self._fields["address"].setText(p["address"] or not_set)
        self._fields["status"].setText(
            t("gui.patients.active") if p["active"] else t("gui.patients.inactive")
        )

        self.toggle_button.setText(
            t("gui.patients.deactivate") if p["active"] else t("gui.patients.reactivate")
        )
        self.edit_button.setEnabled(Permission.EDIT_PATIENT in perms)
        self.toggle_button.setEnabled(Permission.DEACTIVATE_PATIENT in perms)
        self.delete_button.setEnabled(Permission.DELETE_PATIENT in perms)
        self.attach_button.setEnabled(Permission.ATTACH_FILE in perms)
        self.history_button.setVisible(Permission.VIEW_HISTORY in perms)

        self.attach_list.clear()
        for a in data["attachments"]:
            title = a["description"] or Path(a["file_path"]).name
            item = QListWidgetItem(f"{title}\n{a['file_path']}")
            item.setData(Qt.ItemDataRole.UserRole, a["id"])
            item.setToolTip(a["file_path"])
            self.attach_list.addItem(item)
        self.empty_label.setVisible(not data["attachments"])
        self.attach_list.setVisible(bool(data["attachments"]))
        self.history_table.set_rows(data["transactions"])
        self.history_empty.setVisible(not data["transactions"])
        self.history_table.setVisible(bool(data["transactions"]))

    # --- actions ---------------------------------------------------------------

    def _edit(self) -> None:
        def save(values: dict, parent) -> bool:
            ok, _ = run_logic(
                parent,
                self.controller,
                lambda db, user: patients.edit_patient(
                    db, patient_id=self._patient_id, acting_user=user, **values
                ),
            )
            return ok

        dialog = PatientFormDialog(
            self, title=t("gui.patients.edit_title"), save=save, initial=self._patient
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load(self._patient_id)

    def _history(self) -> None:
        show_history(
            self,
            self.controller,
            table_name="patients",
            record_id=self._patient_id,
            title=self._patient["full_name"],
        )

    def _toggle_active(self) -> None:
        activate = not self._patient["active"]
        key = "gui.patients.confirm_reactivate" if activate else "gui.patients.confirm_deactivate"
        if not confirm(self, t(key, name=self._patient["full_name"])):
            return
        action = patients.reactivate_patient if activate else patients.deactivate_patient
        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: action(db, patient_id=self._patient_id, acting_user=user),
        )
        if ok:
            self.load(self._patient_id)

    def _delete(self) -> None:
        if not confirm(self, t("gui.patients.confirm_delete", name=self._patient["full_name"])):
            return

        def do_delete(db, user):
            try:
                patients.delete_patient(db, patient_id=self._patient_id, acting_user=user)
            except PatientHasTransactionsError:
                return "blocked"
            return "deleted"

        ok, outcome = run_logic(self, self.controller, do_delete)
        if not ok:
            return
        if outcome == "deleted":
            self.back_requested.emit()
            return

        # Has financial history: offer deactivation instead (task plan 2.1).
        question = f"{t('patients.delete_blocked_has_transactions')}\n\n{t('gui.patients.deactivate_now')}"
        if confirm(self, question):
            ok, _ = run_logic(
                self,
                self.controller,
                lambda db, user: patients.deactivate_patient(
                    db, patient_id=self._patient_id, acting_user=user
                ),
            )
            if ok:
                self.load(self._patient_id)

    def _attach(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, t("gui.attachments.pick_title"))
        if not path:
            return
        path = os.path.normpath(path)

        dialog = QInputDialog(self)
        dialog.setWindowTitle(t("gui.attachments.desc_title"))
        dialog.setLabelText(t("gui.attachments.desc_label"))
        dialog.setOkButtonText(t("gui.save"))
        dialog.setCancelButtonText(t("gui.cancel"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        description = dialog.textValue()

        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: patients.attach_file(
                db,
                patient_id=self._patient_id,
                file_path=path,
                acting_user=user,
                description=description,
            ),
        )
        if ok:
            self.load(self._patient_id)

    def _open_attachment(self) -> None:
        item = self.attach_list.currentItem()
        if item is None:
            show_message(self, t("gui.attachments.select_first"))
            return
        attachment_id = item.data(Qt.ItemDataRole.UserRole)
        # A missing/moved file raises AttachmentNotFoundError -> shown as a message by run_logic.
        run_logic(
            self,
            self.controller,
            lambda db, user: attachments.open_attachment(db, attachment_id),
        )
