"""
Adjustments screen (task plan Phase 4, admin-only): correct a saved
transaction by recording a signed adjustment (or void it entirely). Nothing
is edited or deleted — see logic/adjustments.py.
"""

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
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
from gui.patient_picker import PatientPicker
from gui.transaction_table import TransactionTable, _local
from i18n import format_currency, format_datetime, t
from logic import adjustments, transactions
from logic.errors import LogicError

_BLANK = "—"


class AdjustmentsPage(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._rows: list = []  # TransactionRow list backing txn_table

        self.picker = PatientPicker(controller)
        self.picker.changed.connect(self._load_patient_transactions)

        self.txn_table = TransactionTable(show_patient=False)
        self.txn_table.setMaximumHeight(170)
        self.txn_table.itemSelectionChanged.connect(self._update_preview)
        self.txn_hint = QLabel(t("gui.adjustments.pick_patient"))

        self.amount = QLineEdit()
        self.amount.setPlaceholderText("-50.00")
        self.amount.textChanged.connect(lambda _text: self._update_preview())
        void_button = QPushButton(t("gui.adjustments.void"))
        void_button.clicked.connect(self._fill_void)
        amount_row = QHBoxLayout()
        amount_row.addWidget(self.amount, 1)
        amount_row.addWidget(void_button)
        self.reason = QLineEdit()

        form = QFormLayout()
        form.addRow(t("gui.transactions.patient"), self.picker)
        form.addRow(t("gui.adjustments.transaction"), self.txn_table)
        form.addRow("", self.txn_hint)
        form.addRow(t("fields.adjustment_amount"), amount_row)
        form.addRow(t("fields.reason"), self.reason)

        note = QLabel(t("gui.adjustments.note"))
        note.setWordWrap(True)
        self.preview = QLabel(_BLANK)
        self.preview.setWordWrap(True)
        preview_box = QGroupBox(t("gui.adjustments.preview_title"))
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.addWidget(self.preview)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #1b7f3b;")
        self.status_label.setVisible(False)
        self.save_button = QPushButton(t("gui.adjustments.save"))
        self.save_button.clicked.connect(self._save)
        save_row = QHBoxLayout()
        save_row.addWidget(self.status_label, 1)
        save_row.addWidget(self.save_button)

        entry_box = QGroupBox(t("gui.adjustments.new_title"))
        entry_layout = QVBoxLayout(entry_box)
        entry_layout.addWidget(note)
        entry_layout.addLayout(form)
        entry_layout.addWidget(preview_box)
        entry_layout.addLayout(save_row)

        self.recent = QTableWidget(0, 8)
        self.recent.setHorizontalHeaderLabels(
            [
                t("gui.transactions.col_date"),
                t("gui.transactions.col_patient"),
                t("gui.transactions.col_doctor"),
                t("gui.adjustments.col_change"),
                t("gui.transactions.col_doctor_share"),
                t("gui.transactions.col_center_share"),
                t("fields.reason"),
                t("gui.adjustments.col_by"),
            ]
        )
        self.recent.verticalHeader().setVisible(False)
        self.recent.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recent.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.recent.horizontalHeader()
        for col in range(8):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        recent_box = QGroupBox(t("gui.adjustments.recent"))
        recent_layout = QVBoxLayout(recent_box)
        recent_layout.addWidget(self.recent)

        layout = QVBoxLayout(self)
        layout.addWidget(entry_box)
        layout.addWidget(recent_box, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_recent()

    # --- data ------------------------------------------------------------------

    def _load_patient_transactions(self) -> None:
        patient_id = self.picker.selected_id()
        if patient_id is None:
            return
        ok, rows = run_logic(
            self,
            self.controller,
            lambda db, user: transactions.list_transaction_rows(
                db, acting_user=user, patient_id=patient_id, limit=100
            ),
        )
        if not ok:
            return
        self._rows = rows
        self.txn_table.set_rows(rows)
        self.txn_hint.setText(
            t("gui.adjustments.select_transaction") if rows else t("gui.adjustments.no_transactions")
        )
        self._update_preview()

    def _refresh_recent(self) -> None:
        ok, rows = run_logic(
            self,
            self.controller,
            lambda db, user: adjustments.list_adjustment_rows(db, acting_user=user, limit=100),
        )
        if not ok:
            return
        number_align = Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter
        self.recent.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [
                (format_datetime(_local(row.created_at), format="short"), None),
                (row.patient_name, None),
                (row.doctor_name, None),
                (format_currency(row.total_amount), number_align),
                (format_currency(row.doctor_amount), number_align),
                (format_currency(row.center_amount), number_align),
                (row.reason, None),
                (row.recorded_by_name, None),
            ]
            for c, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                if align is not None:
                    item.setTextAlignment(align)
                item.setToolTip(text)
                self.recent.setItem(r, c, item)

    # --- preview ---------------------------------------------------------------

    def _selected_row(self):
        index = self.txn_table.currentRow()
        if index < 0 or index >= len(self._rows):
            return None
        return self._rows[index]

    def _compute(self):
        """
        Returns (row, change, (new_net_total, new_net_doctor, new_net_center)).
        Raises LogicError (nothing selected / invalid change) or ArithmeticError
        (unparseable text). Uses the logic layer's calculate_adjustment, so the
        preview always matches what gets saved.
        """
        row = self._selected_row()
        if row is None:
            raise LogicError(t("gui.adjustments.select_transaction_first"))
        change = Decimal(self.amount.text().strip())
        net_total = row.total_amount + row.adjusted_total
        net_doctor = row.doctor_amount + row.adjusted_doctor
        net_center = row.center_amount + row.adjusted_center
        adj_total, adj_doctor, adj_center = adjustments.calculate_adjustment(
            row.doctor_percentage, net_total, net_doctor, net_center, change
        )
        return row, change, (net_total + adj_total, net_doctor + adj_doctor, net_center + adj_center)

    def _update_preview(self) -> None:
        try:
            _row, _change, (total, doctor, center) = self._compute()
        except (LogicError, ArithmeticError):
            self.preview.setText(_BLANK)
            return
        self.preview.setText(
            t(
                "gui.adjustments.preview",
                net=format_currency(total),
                doctor=format_currency(doctor),
                center=format_currency(center),
            )
        )

    def _fill_void(self) -> None:
        row = self._selected_row()
        if row is None:
            show_message(self, t("gui.adjustments.select_transaction_first"))
            return
        self.amount.setText(str(-(row.total_amount + row.adjusted_total)))

    # --- saving ----------------------------------------------------------------

    def _save(self) -> None:
        self.status_label.setVisible(False)
        try:
            row, change, (total, doctor, center) = self._compute()
        except LogicError as exc:
            show_message(self, str(exc))
            return
        except ArithmeticError:
            show_message(self, t("validation.not_a_number", field=t("fields.adjustment_amount")))
            return

        question = t(
            "gui.adjustments.confirm",
            patient=row.patient_name,
            doctor=row.doctor_name,
            change=format_currency(change),
            net=format_currency(total),
            doctor_amount=format_currency(doctor),
            center_amount=format_currency(center),
            reason=self.reason.text().strip(),
        )
        if not confirm(self, question):
            return

        reason = self.reason.text()
        ok, _ = run_logic(
            self,
            self.controller,
            lambda db, user: adjustments.record_adjustment(
                db,
                transaction_id=row.id,
                amount_change=change,
                reason=reason,
                acting_user=user,
            ).id,
        )
        if not ok:
            return

        self.amount.clear()
        self.reason.clear()
        self.status_label.setText(t("gui.adjustments.recorded"))
        self.status_label.setVisible(True)
        self._load_patient_transactions()
        self._refresh_recent()