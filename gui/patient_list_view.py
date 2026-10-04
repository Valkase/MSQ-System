"""Patient list / search view (task plan Phase 4)."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
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

from gui.actions import run_logic
from gui.patient_form import PatientFormDialog
from i18n import t
from logic import patients

SEARCH_DEBOUNCE_MS = 300


class PatientListView(QWidget):
    patient_selected = Signal(object)  # emits the patient's uuid.UUID

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._loaded = False

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("gui.patients.search_placeholder"))
        self.search.setClearButtonEnabled(True)
        self.show_inactive = QCheckBox(t("gui.patients.show_inactive"))
        new_button = QPushButton(t("gui.patients.new"))
        new_button.clicked.connect(self._new_patient)

        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.show_inactive)
        top.addWidget(new_button)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [t("gui.patients.col_name"), t("gui.patients.col_phone"), t("gui.patients.col_status")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._open_row(row))

        self.count_label = QLabel()
        open_button = QPushButton(t("gui.patients.open"))
        open_button.clicked.connect(lambda: self._open_row(self.table.currentRow()))
        bottom = QHBoxLayout()
        bottom.addWidget(self.count_label, 1)
        bottom.addWidget(open_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

        # Debounce typing so we don't query on every keystroke.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _text: self._timer.start())
        self.show_inactive.toggled.connect(lambda _checked: self.refresh())

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:  # first time this page is actually shown
            self._loaded = True
            self.refresh()

    def refresh(self) -> None:
        query = self.search.text().strip()
        include_inactive = self.show_inactive.isChecked()

        def fetch(db, user):
            if query:
                rows = patients.search_patients(db, query, include_inactive=include_inactive)
            else:
                rows = patients.list_recent_patients(db, include_inactive=include_inactive)
            return [(p.id, p.full_name, p.phone, p.active) for p in rows]

        ok, rows = run_logic(self, self.controller, fetch)
        if not ok:
            return

        self.table.setRowCount(len(rows))
        grey = QBrush(QColor("#888888"))
        for row, (patient_id, name, phone, active) in enumerate(rows):
            status = t("gui.patients.active") if active else t("gui.patients.inactive")
            for col, text in enumerate((name, phone, status)):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, patient_id)
                if not active:
                    item.setForeground(grey)
                self.table.setItem(row, col, item)
        self.count_label.setText(t("gui.patients.count", count=len(rows)))

    def _open_row(self, row: int) -> None:
        if row < 0:
            return
        patient_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self.patient_selected.emit(patient_id)

    def _new_patient(self) -> None:
        created: dict = {}

        def save(values: dict, parent) -> bool:
            ok, patient_id = run_logic(
                parent,
                self.controller,
                lambda db, user: patients.create_patient(db, acting_user=user, **values).id,
            )
            if ok:
                created["id"] = patient_id
            return ok

        dialog = PatientFormDialog(self, title=t("gui.patients.new_title"), save=save)
        if dialog.exec() == QDialog.DialogCode.Accepted and "id" in created:
            self.patient_selected.emit(created["id"])  # jump straight to the new profile