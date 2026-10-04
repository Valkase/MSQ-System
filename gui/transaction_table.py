"""Read-only transaction table, shared by the transactions screen and the patient billing history."""

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from i18n import format_currency, format_datetime, t


def _local(value: datetime) -> datetime:
    """created_at is stored in UTC; show it in the PC's local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone()

def _with_net(value, adjustment) -> str:
    text = format_currency(value)
    if adjustment:
        text += "  " + t("gui.transactions.net_suffix", amount=format_currency(value + adjustment))
    return text


class TransactionTable(QTableWidget):
    def __init__(self, *, show_patient: bool):
        keys = (
            ["col_date"]
            + (["col_patient"] if show_patient else [])
            + ["col_doctor", "col_total", "col_doctor_share", "col_center_share", "col_description"]
        )
        super().__init__(0, len(keys))
        self._show_patient = show_patient

        self.setHorizontalHeaderLabels([t(f"gui.transactions.{key}") for key in keys])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.horizontalHeader()
        for col in range(len(keys) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(keys) - 1, QHeaderView.ResizeMode.Stretch)

    def set_rows(self, rows) -> None:
        """`rows` is a list of logic.transactions.TransactionRow."""
        number_align = Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [(format_datetime(_local(row.created_at), format="short"), None)]
            if self._show_patient:
                cells.append((row.patient_name, None))
            cells += [
                (row.doctor_name, None),
                (_with_net(row.total_amount, row.adjusted_total), number_align),
                (_with_net(row.doctor_amount, row.adjusted_doctor), number_align),
                (_with_net(row.center_amount, row.adjusted_center), number_align),
                (row.description or "", None),
            ]
            for c, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                if align is not None:
                    item.setTextAlignment(align)
                item.setToolTip(text)
                self.setItem(r, c, item)