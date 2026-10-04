"""Unit tests for logic/attachments.py (task plan 2.1 'open an attachment', Phase 6 missing-path test)."""

import uuid

import pytest

from i18n import set_locale
from logic import attachments, patients
from logic.errors import AttachmentNotFoundError, AttachmentOpenError, NotFoundError


def _attach(session, user, path):
    patient = patients.create_patient(
        session, full_name="Mona Youssef", phone="0100000001", acting_user=user
    )
    return patients.attach_file(
        session, patient_id=patient.id, file_path=str(path), acting_user=user
    )


def test_open_attachment_launches_an_existing_file(session, receptionist_user, tmp_path):
    f = tmp_path / "lab.pdf"
    f.write_text("x")
    att = _attach(session, receptionist_user, f)

    launched = []
    attachments.open_attachment(session, att.id, launcher=launched.append)

    assert launched == [f]


def test_missing_file_raises_a_clear_error_and_never_launches(session, receptionist_user, tmp_path):
    att = _attach(session, receptionist_user, tmp_path / "moved.pdf")  # never created

    launched = []
    with pytest.raises(AttachmentNotFoundError) as exc:
        attachments.open_attachment(session, att.id, launcher=launched.append)

    assert launched == []
    assert str(tmp_path / "moved.pdf") in str(exc.value)


def test_missing_file_message_is_localized(session, receptionist_user, tmp_path):
    att = _attach(session, receptionist_user, tmp_path / "moved.pdf")
    set_locale("ar")
    with pytest.raises(AttachmentNotFoundError) as exc:
        attachments.open_attachment(session, att.id, launcher=lambda p: None)
    assert "??" not in str(exc.value)


def test_a_directory_is_not_a_openable_file(session, receptionist_user, tmp_path):
    att = _attach(session, receptionist_user, tmp_path)  # a folder, not a file
    with pytest.raises(AttachmentNotFoundError):
        attachments.open_attachment(session, att.id, launcher=lambda p: None)


def test_launcher_failure_becomes_attachment_open_error(session, receptionist_user, tmp_path):
    f = tmp_path / "scan.png"
    f.write_text("x")
    att = _attach(session, receptionist_user, f)

    def boom(_path):
        raise OSError("no viewer installed")

    with pytest.raises(AttachmentOpenError):
        attachments.open_attachment(session, att.id, launcher=boom)


def test_unknown_attachment_id_raises_not_found(session):
    with pytest.raises(NotFoundError):
        attachments.open_attachment(session, uuid.uuid4(), launcher=lambda p: None)