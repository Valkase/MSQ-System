"""Search-and-pick widget for choosing one (active) patient."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from gui.actions import run_logic
from i18n import t
from logic import patients

SEARCH_DEBOUNCE_MS = 300
MAX_RESULTS = 50


class PatientPicker(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._id = None
        self._name = None

        self.search = QLineEdit()
        self.search.setPlaceholderText(t("gui.transactions.patient_search_placeholder"))
        self.search.setClearButtonEnabled(True)
        self.results = QListWidget()
        self.results.setMaximumHeight(110)
        self.selected_label = QLabel(t("gui.transactions.no_patient_selected"))
        font = self.selected_label.font()
        font.setBold(True)
        self.selected_label.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.search)
        layout.addWidget(self.results)
        layout.addWidget(self.selected_label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _text: self._timer.start())
        self.results.itemClicked.connect(self._choose)
        self.results.itemActivated.connect(self._choose)

    def selected_id(self):
        return self._id

    def selected_name(self) -> str | None:
        return self._name

    def clear(self) -> None:
        self._id = None
        self._name = None
        self.search.clear()
        self.results.clear()
        self.selected_label.setText(t("gui.transactions.no_patient_selected"))

    def _run_search(self) -> None:
        query = self.search.text().strip()
        if not query:
            self.results.clear()
            return

        ok, rows = run_logic(
            self,
            self.controller,
            lambda db, user: [
                (p.id, p.full_name, p.phone) for p in patients.search_patients(db, query)
            ],
        )
        if not ok:
            return
        self.results.clear()
        for patient_id, name, phone in rows[:MAX_RESULTS]:
            item = QListWidgetItem(f"{name} — {phone}")
            item.setData(Qt.ItemDataRole.UserRole, (patient_id, name))
            self.results.addItem(item)

    def _choose(self, item: QListWidgetItem) -> None:
        self._id, self._name = item.data(Qt.ItemDataRole.UserRole)
        self.selected_label.setText(t("gui.transactions.selected_patient", name=self._name))