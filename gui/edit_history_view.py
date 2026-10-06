"""
Edit-history view (task plan Phase 4): a read-only dialog listing every
audit_log entry for one patient or doctor — who changed what, from what to
what, and when. Reads through logic.audit.list_history_entries, which is
admin-only (VIEW_HISTORY).

Use the helper from any screen:

    show_history(self, self.controller, table_name="patients",
                 record_id=patient_id, title=patient_name)
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from gui.actions import run_logic
from gui.transaction_table import _local
from i18n import format_date, format_datetime, format_number, t
from logic import audit

_COLUMNS = ("date", "by", "action", "field", "old", "new")


def _field_label(field: str) -> str:
    key = f"gui.history.field.{field}"
    label = t(key)
    return field if label == f"??{key}??" else label  # unknown field: show raw name


def _format_value(field: str, value) -> str:
    if value is None:
        return t("gui.patients.not_set")
    if field == "active" and isinstance(value, bool):
        return t("gui.status.active") if value else t("gui.status.inactive")
    if field == "date_of_birth":
        try:
            return format_date(date.fromisoformat(str(value)), format="long")
        except ValueError:
            return str(value)
    if field == "standard_percentage":
        try:
            return f"{format_number(Decimal(str(value)))}%"
        except InvalidOperation:
            return str(value)
    return str(value)


class EditHistoryDialog(QDialog):
    def __init__(self, parent, controller, *, table_name: str, record_id, title: str):
        super().__init__(parent)
        self.controller = controller
        self._table_name = table_name
        self._record_id = record_id
        self.setWindowTitle(t("gui.history.title", name=title))
        self.setMinimumSize(820, 440)

        self.empty_label = QLabel(t("gui.history.empty"))
        self.empty_label.setVisible(False)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([t(f"gui.history.col_{c}") for c in _COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        for col in range(len(_COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        close = QPushButton(t("gui.close"))
        close.clicked.connect(self.accept)
        close.setDefault(True)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

    def load(self) -> bool:
        """Fetch and render. Returns False if it failed (message / login screen already shown)."""
        ok, entries = run_logic(
            self,
            self.controller,
            lambda db, user: audit.list_history_entries(
                db, table_name=self._table_name, record_id=self._record_id, acting_user=user
            ),
        )
        if not ok:
            return False

        rows = []
        for entry in entries:
            stamp = format_datetime(_local(entry.created_at), format="short")
            action = t(f"gui.history.action_{entry.action}")
            if entry.changes:
                for c in entry.changes:
                    rows.append(
                        (
                            stamp,
                            entry.changed_by_name,
                            action,
                            _field_label(c.field),
                            _format_value(c.field, c.old),
                            _format_value(c.field, c.new),
                        )
                    )
            else:
                rows.append((stamp, entry.changed_by_name, action, "", "", ""))

        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(r, c, item)
        self.empty_label.setVisible(not rows)
        self.table.setVisible(bool(rows))
        return True


def show_history(parent, controller, *, table_name: str, record_id, title: str) -> None:
    """Open the history dialog for one record (does nothing if loading fails)."""
    dialog = EditHistoryDialog(
        parent, controller, table_name=table_name, record_id=record_id, title=title
    )
    if dialog.load():
        dialog.exec()
