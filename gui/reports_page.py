"""
Reports screen (task plan Phase 4): custom date range, center totals, and
per-doctor totals. Read-only; the numbers come from logic/reports.py, which
sums in SQL, so this screen only formats them.
"""

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.actions import run_logic
from i18n import format_currency, format_date, format_number, t
from logic import reports


def _date_edit(value: QDate) -> QDateEdit:
    edit = QDateEdit(value)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy-MM-dd")
    return edit


class ReportsPage(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        today = QDate.currentDate()
        self.start = _date_edit(QDate(today.year(), today.month(), 1))
        self.end = _date_edit(today)

        run_button = QPushButton(t("gui.reports.run"))
        run_button.clicked.connect(self.refresh)
        today_button = QPushButton(t("gui.reports.preset_today"))
        today_button.clicked.connect(lambda: self._preset(QDate.currentDate(), QDate.currentDate()))
        month_button = QPushButton(t("gui.reports.preset_month"))
        month_button.clicked.connect(self._preset_month)
        last30_button = QPushButton(t("gui.reports.preset_30"))
        last30_button.clicked.connect(
            lambda: self._preset(QDate.currentDate().addDays(-29), QDate.currentDate())
        )

        picker = QHBoxLayout()
        picker.addWidget(QLabel(t("gui.reports.from")))
        picker.addWidget(self.start)
        picker.addWidget(QLabel(t("gui.reports.to")))
        picker.addWidget(self.end)
        picker.addWidget(run_button)
        picker.addStretch()
        picker.addWidget(today_button)
        picker.addWidget(month_button)
        picker.addWidget(last30_button)

        self.range_label = QLabel()
        self.empty_label = QLabel(t("gui.reports.empty"))
        self.empty_label.setVisible(False)

        self.sum_count = QLabel("—")
        self.sum_total = QLabel("—")
        self.sum_doctors = QLabel("—")
        self.sum_center = QLabel("—")
        summary_form = QFormLayout()
        summary_form.addRow(t("gui.reports.transactions"), self.sum_count)
        summary_form.addRow(t("gui.reports.total_billed"), self.sum_total)
        summary_form.addRow(t("gui.reports.doctors_share"), self.sum_doctors)
        summary_form.addRow(t("gui.reports.center_share"), self.sum_center)
        summary_box = QGroupBox(t("gui.reports.summary_title"))
        summary_box.setLayout(summary_form)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                t("gui.reports.col_doctor"),
                t("gui.reports.col_count"),
                t("gui.transactions.col_total"),
                t("gui.transactions.col_doctor_share"),
                t("gui.transactions.col_center_share"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        doctors_box = QGroupBox(t("gui.reports.doctors_title"))
        doctors_layout = QVBoxLayout(doctors_box)
        doctors_layout.addWidget(self.table)

        layout = QVBoxLayout(self)
        layout.addLayout(picker)
        layout.addWidget(self.range_label)
        layout.addWidget(self.empty_label)
        layout.addWidget(summary_box)
        layout.addWidget(doctors_box, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    # --- presets ---------------------------------------------------------------

    def _preset(self, start: QDate, end: QDate) -> None:
        self.start.setDate(start)
        self.end.setDate(end)
        self.refresh()

    def _preset_month(self) -> None:
        today = QDate.currentDate()
        self._preset(QDate(today.year(), today.month(), 1), today)

    # --- data ------------------------------------------------------------------

    def refresh(self) -> None:
        start = self.start.date().toPython()
        end = self.end.date().toPython()

        def fetch(db, user):
            return {
                "center": reports.center_totals_for_range(
                    db, start_date=start, end_date=end, acting_user=user
                ),
                "doctors": reports.doctor_totals_for_range(
                    db, start_date=start, end_date=end, acting_user=user
                ),
            }

        # An invalid range (end before start) comes back as a message box from run_logic.
        ok, data = run_logic(self, self.controller, fetch)
        if not ok:
            return

        center = data["center"]
        self.range_label.setText(
            t(
                "gui.reports.range_shown",
                start=format_date(start, format="long"),
                end=format_date(end, format="long"),
            )
        )
        self.empty_label.setVisible(center.transaction_count == 0)
        self.sum_count.setText(format_number(center.transaction_count))
        self.sum_total.setText(format_currency(center.total_amount))
        self.sum_doctors.setText(format_currency(center.doctor_amount))
        self.sum_center.setText(format_currency(center.center_amount))

        number_align = Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter
        rows = data["doctors"]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [
                (row.doctor_name, None),
                (format_number(row.transaction_count), number_align),
                (format_currency(row.total_amount), number_align),
                (format_currency(row.doctor_amount), number_align),
                (format_currency(row.center_amount), number_align),
            ]
            for c, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                if align is not None:
                    item.setTextAlignment(align)
                self.table.setItem(r, c, item)