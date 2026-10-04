"""
Transactions screen (task plan Phase 4): new-transaction entry with a live
doctor/center split preview, plus a table of recent transactions. There is
deliberately no edit or delete here, since saved transactions are immutable.
"""

from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.actions import confirm, run_logic, show_message
from gui.patient_picker import PatientPicker
from gui.transaction_table import TransactionTable
from i18n import format_currency, format_number, t
from logic import doctors, transactions
from logic.errors import LogicError

_BLANK = "—"


class TransactionsPage(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        self.picker = PatientPicker(controller)
        self.doctor = QComboBox()
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.00")
        self.description = QLineEdit()

        form = QFormLayout()
        form.addRow(t("gui.transactions.patient"), self.picker)
        form.addRow(t("gui.transactions.doctor"), self.doctor)
        form.addRow(t("fields.total_amount"), self.amount)
        form.addRow(t("fields.description"), self.description)

        self.preview_doctor = QLabel(_BLANK)
        self.preview_center = QLabel(_BLANK)
        preview_box = QGroupBox(t("gui.transactions.preview_title"))
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(self.preview_doctor)
        preview_layout.addWidget(self.preview_center)

        self.no_doctors_label = QLabel(t("gui.transactions.no_doctors"))
        self.no_doctors_label.setWordWrap(True)
        self.no_doctors_label.setStyleSheet("color: #b00020;")
        self.no_doctors_label.setVisible(False)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #1b7f3b;")
        self.status_label.setVisible(False)
        self.save_button = QPushButton(t("gui.transactions.save"))
        self.save_button.clicked.connect(self._save)

        save_row = QHBoxLayout()
        save_row.addWidget(self.status_label, 1)
        save_row.addWidget(self.save_button)

        entry_box = QGroupBox(t("gui.transactions.new_title"))
        entry_layout = QVBoxLayout(entry_box)
        entry_layout.addLayout(form)
        entry_layout.addWidget(preview_box)
        entry_layout.addWidget(self.no_doctors_label)
        entry_layout.addLayout(save_row)

        self.table = TransactionTable(show_patient=True)
        self.count_label = QLabel()
        recent_box = QGroupBox(t("gui.transactions.recent"))
        recent_layout = QVBoxLayout(recent_box)
        recent_layout.addWidget(self.table, 1)
        recent_layout.addWidget(self.count_label)

        layout = QVBoxLayout(self)
        layout.addWidget(entry_box)
        layout.addWidget(recent_box, 1)

        self.doctor.currentIndexChanged.connect(lambda _i: self._update_preview())
        self.amount.textChanged.connect(lambda _text: self._update_preview())

    def showEvent(self, event):
        super().showEvent(event)
        # Reload every time the page is shown: doctors/rates may have changed.
        self._load_doctors()
        self.refresh_history()

    # --- data ------------------------------------------------------------------

    def _load_doctors(self) -> None:
        ok, rows = run_logic(
            self,
            self.controller,
            lambda db, user: [
                (d.id, d.name, d.standard_percentage) for d in doctors.list_doctors(db)
            ],
        )
        if not ok:
            return

        previous = self.doctor.currentData()
        previous_id = previous[0] if previous else None
        self.doctor.blockSignals(True)
        self.doctor.clear()
        for doctor_id, name, pct in rows:
            self.doctor.addItem(f"{name} ({format_number(pct)}%)", (doctor_id, pct, name))
        for index in range(self.doctor.count()):
            if self.doctor.itemData(index)[0] == previous_id:
                self.doctor.setCurrentIndex(index)
                break
        self.doctor.blockSignals(False)

        self.no_doctors_label.setVisible(not rows)
        self.save_button.setEnabled(bool(rows))
        self._update_preview()

    def refresh_history(self) -> None:
        ok, rows = run_logic(
            self,
            self.controller,
            lambda db, user: transactions.list_transaction_rows(db, acting_user=user, limit=100),
        )
        if not ok:
            return
        self.table.set_rows(rows)
        self.count_label.setText(t("gui.transactions.count", count=len(rows)))

    # --- split preview ---------------------------------------------------------

    def _compute(self):
        """
        Returns (doctor_id, doctor_name, doctor_pct, total, doctor_amount, center_amount).
        Raises LogicError (bad amount, no doctor) or ArithmeticError (unparseable text).
        Uses the logic layer's calculate_split, so the preview always matches what gets saved.
        """
        data = self.doctor.currentData()
        if data is None:
            raise LogicError(t("gui.transactions.no_doctors"))
        doctor_id, pct, name = data
        total = Decimal(self.amount.text().strip())
        doctor_amount, center_amount = transactions.calculate_split(total, pct)
        return doctor_id, name, pct, total, doctor_amount, center_amount

    def _update_preview(self) -> None:
        try:
            _id, _name, pct, _total, doctor_amount, center_amount = self._compute()
        except (LogicError, ArithmeticError):
            self.preview_doctor.setText(_BLANK)
            self.preview_center.setText(_BLANK)
            return
        center_pct = Decimal(100) - pct
        self.preview_doctor.setText(
            f"{t('gui.transactions.preview_doctor', pct=format_number(pct))}: "
            f"{format_currency(doctor_amount)}"
        )
        self.preview_center.setText(
            f"{t('gui.transactions.preview_center', pct=format_number(center_pct))}: "
            f"{format_currency(center_amount)}"
        )

    # --- saving ----------------------------------------------------------------

    def _save(self) -> None:
        self.status_label.setVisible(False)

        patient_id = self.picker.selected_id()
        if patient_id is None:
            show_message(self, t("gui.transactions.select_patient_first"))
            return
        try:
            doctor_id, doctor_name, pct, total, doctor_amount, center_amount = self._compute()
        except LogicError as exc:
            show_message(self, str(exc))
            return
        except ArithmeticError:
            show_message(self, t("validation.not_a_number", field=t("fields.total_amount")))
            return

        question = t(
            "gui.transactions.confirm",
            amount=format_currency(total),
            patient=self.picker.selected_name(),
            doctor=doctor_name,
            doctor_amount=format_currency(doctor_amount),
            doctor_pct=format_number(pct),
            center_amount=format_currency(center_amount),
            center_pct=format_number(Decimal(100) - pct),
        )
        if not confirm(self, question):
            return

        description = self.description.text()
        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: transactions.record_transaction(
                db,
                patient_id=patient_id,
                doctor_id=doctor_id,
                total_amount=total,
                acting_user=user,
                description=description,
            ).id,
        )
        if not ok:
            return

        self.amount.clear()
        self.description.clear()
        self.picker.clear()
        self.status_label.setText(t("gui.transactions.recorded"))
        self.status_label.setVisible(True)
        self.refresh_history()