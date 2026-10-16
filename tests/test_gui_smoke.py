"""
Phase 6 (English/Arabic + RTL), automated half: build real screens headless
in both languages, assert no missing-translation markers and the correct
layout direction. Real-screen review is still manual (see the checklist).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton  # noqa: E402

from i18n import get_locale, set_locale, t  # noqa: E402

LTR, RTL = Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=["en", "ar"])
def locale_code(request, qapp):
    set_locale(request.param)
    qapp.setLayoutDirection(RTL if request.param == "ar" else LTR)
    yield request.param
    qapp.setLayoutDirection(LTR)  # i18n locale itself is reset by conftest


def _texts(widget) -> list[str]:
    found = [widget.windowTitle()]
    for cls in (QLabel, QPushButton, QCheckBox):
        found += [w.text() for w in widget.findChildren(cls)]
    return [x for x in found if x]


class StubController:
    """Just enough of AppController for screens that only build (no DB access)."""

    def schema_status(self):
        return None

    def change_language(self, code):
        pass

    def show_main(self, page=0):
        pass

    def show_login(self, message=None):
        pass


def test_login_screen_builds_in_both_languages(locale_code, qapp):
    from gui.login_screen import LoginScreen

    screen = LoginScreen(StubController())
    texts = _texts(screen)

    assert texts, "login screen rendered no text"
    assert not [x for x in texts if "??" in x], texts
    assert screen.isRightToLeft() == (locale_code == "ar")
    combo = screen.findChild(QComboBox)
    assert {combo.itemData(i) for i in range(combo.count())} == {"en", "ar"}
    screen.close()


def test_patient_form_builds_in_both_languages(locale_code, qapp):
    from gui.patient_form import PatientFormDialog

    dialog = PatientFormDialog(None, title=t("gui.patients.new_title"), save=lambda v, p: True)

    assert not [x for x in _texts(dialog) if "??" in x]
    assert dialog.isRightToLeft() == (locale_code == "ar")
    dialog.close()


def test_password_dialog_builds_in_both_languages(locale_code, qapp):
    from gui.password_dialog import PasswordDialog

    dialog = PasswordDialog(
        None, title=t("gui.change_password.title"), save=lambda v, p: True, ask_current=True
    )

    assert not [x for x in _texts(dialog) if "??" in x]
    assert dialog.isRightToLeft() == (locale_code == "ar")
    dialog.close()


def test_user_form_builds_in_both_languages(locale_code, qapp):
    from gui.users_page import UserFormDialog

    dialog = UserFormDialog(None, save=lambda v, p: True)

    assert not [x for x in _texts(dialog) if "??" in x]
    assert dialog.isRightToLeft() == (locale_code == "ar")
    dialog.close()


@pytest.fixture(scope="module")
def controller(qapp):
    from gui.app import AppController

    return AppController(qapp)


@pytest.mark.parametrize("code,direction", [("ar", RTL), ("en", LTR)])
def test_controller_applies_layout_direction_with_the_language(controller, qapp, code, direction):
    try:
        controller._apply_locale(code)
        assert get_locale() == code
        assert qapp.layoutDirection() == direction
    finally:
        qapp.setLayoutDirection(LTR)


def test_unsupported_saved_language_falls_back_to_english(controller, qapp):
    try:
        controller._apply_locale("fr")
        assert get_locale() == "en"
        assert qapp.layoutDirection() == LTR
    finally:
        qapp.setLayoutDirection(LTR)