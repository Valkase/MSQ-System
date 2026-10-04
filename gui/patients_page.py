"""The 'Patients' navigation page: list <-> profile."""

from PySide6.QtWidgets import QStackedWidget

from gui.patient_list_view import PatientListView
from gui.patient_profile_view import PatientProfileView


class PatientsPage(QStackedWidget):
    def __init__(self, controller):
        super().__init__()
        self.list_view = PatientListView(controller)
        self.profile_view = PatientProfileView(controller)
        self.addWidget(self.list_view)
        self.addWidget(self.profile_view)

        self.list_view.patient_selected.connect(self.open_patient)
        self.profile_view.back_requested.connect(self.show_list)

    def open_patient(self, patient_id) -> None:
        if self.profile_view.load(patient_id):
            self.setCurrentWidget(self.profile_view)

    def show_list(self) -> None:
        self.list_view.refresh()  # pick up edits, deactivations, deletions
        self.setCurrentWidget(self.list_view)