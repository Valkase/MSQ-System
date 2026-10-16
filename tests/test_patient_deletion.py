"""Phase 6: deletion is blocked whenever transactions exist, and clean otherwise."""

from decimal import Decimal

import pytest

from data.models.attachment import Attachment
from data.models.patient import Patient
from data.models.transaction import Transaction
from i18n import set_locale
from logic import adjustments, doctors, patients, transactions
from logic.audit import get_history
from logic.errors import NotFoundError, PatientHasTransactionsError, PermissionDeniedError


def _doctor(session, admin):
    return doctors.create_doctor(
        session, name="Dr. Ahmed Smith", standard_percentage=Decimal("60.00"), acting_user=admin
    )


def _patient(session, user, name="Mona Youssef", phone="0100000001"):
    return patients.create_patient(session, full_name=name, phone=phone, acting_user=user)


def _bill(session, user, patient, doctor, amount="500.00"):
    return transactions.record_transaction(
        session,
        patient_id=patient.id,
        doctor_id=doctor.id,
        total_amount=Decimal(amount),
        acting_user=user,
    )


def test_patient_without_transactions_can_be_deleted(session, receptionist_user):
    patient = _patient(session, receptionist_user)
    pid = patient.id

    patients.delete_patient(session, patient_id=pid, acting_user=receptionist_user)

    assert session.get(Patient, pid) is None


def test_deletion_is_audited_with_a_snapshot(session, receptionist_user):
    patient = _patient(session, receptionist_user)
    pid = patient.id
    patients.delete_patient(session, patient_id=pid, acting_user=receptionist_user)

    last = get_history(session, table_name="patients", record_id=pid)[-1]
    assert last.new_values == {"deleted": True}
    assert last.old_values["full_name"] == "Mona Youssef"


def test_patient_with_a_transaction_cannot_be_deleted(session, admin_user, receptionist_user):
    doctor = _doctor(session, admin_user)
    patient = _patient(session, receptionist_user)
    txn = _bill(session, receptionist_user, patient, doctor)

    with pytest.raises(PatientHasTransactionsError):
        patients.delete_patient(session, patient_id=patient.id, acting_user=receptionist_user)

    assert session.get(Patient, patient.id) is not None
    assert session.get(Transaction, txn.id) is not None
    # a blocked delete must not leave a "deleted" audit entry behind
    assert all(
        h.new_values != {"deleted": True}
        for h in get_history(session, table_name="patients", record_id=patient.id)
    )


def test_fully_voided_transaction_still_blocks_deletion(session, admin_user, receptionist_user):
    doctor = _doctor(session, admin_user)
    patient = _patient(session, receptionist_user)
    txn = _bill(session, receptionist_user, patient, doctor)
    adjustments.record_adjustment(
        session,
        transaction_id=txn.id,
        amount_change=Decimal("-500"),
        reason="void",
        acting_user=admin_user,
    )

    with pytest.raises(PatientHasTransactionsError):
        patients.delete_patient(session, patient_id=patient.id, acting_user=admin_user)


def test_deactivated_patient_with_transactions_is_still_protected(session, admin_user, receptionist_user):
    doctor = _doctor(session, admin_user)
    patient = _patient(session, receptionist_user)
    _bill(session, receptionist_user, patient, doctor)
    patients.deactivate_patient(session, patient_id=patient.id, acting_user=receptionist_user)

    with pytest.raises(PatientHasTransactionsError):
        patients.delete_patient(session, patient_id=patient.id, acting_user=receptionist_user)


def test_after_a_blocked_delete_deactivation_still_works(session, admin_user, receptionist_user):
    doctor = _doctor(session, admin_user)
    patient = _patient(session, receptionist_user)
    _bill(session, receptionist_user, patient, doctor)
    with pytest.raises(PatientHasTransactionsError):
        patients.delete_patient(session, patient_id=patient.id, acting_user=receptionist_user)

    patients.deactivate_patient(session, patient_id=patient.id, acting_user=receptionist_user)
    assert patient.active is False


def test_deleting_one_patient_never_touches_another_patients_history(
    session, admin_user, receptionist_user
):
    doctor = _doctor(session, admin_user)
    keep = _patient(session, receptionist_user, "Keep Me", "0100000002")
    gone = _patient(session, receptionist_user, "Delete Me", "0100000003")
    txn = _bill(session, receptionist_user, keep, doctor)

    patients.delete_patient(session, patient_id=gone.id, acting_user=receptionist_user)

    assert session.get(Patient, keep.id) is not None
    assert session.get(Transaction, txn.id) is not None


def test_attachment_references_are_removed_with_the_patient(session, receptionist_user):
    patient = _patient(session, receptionist_user)
    patients.attach_file(
        session, patient_id=patient.id, file_path="C:/scans/a.pdf", acting_user=receptionist_user
    )
    patients.attach_file(
        session, patient_id=patient.id, file_path="C:/scans/b.pdf", acting_user=receptionist_user
    )

    patients.delete_patient(session, patient_id=patient.id, acting_user=receptionist_user)

    assert session.query(Attachment).count() == 0


def test_deactivated_user_cannot_delete(session, receptionist_user, inactive_receptionist_user):
    patient = _patient(session, receptionist_user)
    with pytest.raises(PermissionDeniedError):
        patients.delete_patient(
            session, patient_id=patient.id, acting_user=inactive_receptionist_user
        )
    assert session.get(Patient, patient.id) is not None


def test_unknown_patient_raises_not_found(session, receptionist_user):
    import uuid

    with pytest.raises(NotFoundError):
        patients.delete_patient(session, patient_id=uuid.uuid4(), acting_user=receptionist_user)


def test_block_message_is_localized(session, admin_user, receptionist_user):
    doctor = _doctor(session, admin_user)
    patient = _patient(session, receptionist_user)
    _bill(session, receptionist_user, patient, doctor)
    set_locale("ar")
    with pytest.raises(PatientHasTransactionsError) as exc:
        patients.delete_patient(session, patient_id=patient.id, acting_user=receptionist_user)
    assert "??" not in str(exc.value)