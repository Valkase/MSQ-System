"""Small reusable widgets shared across GUI screens."""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from i18n import get_locale, t

# Native language names, deliberately NOT translated: a user who can't read
# the current UI language must still be able to find their own.
LANGUAGE_NAMES = {"en": "English", "ar": "العربية"}


class LanguageSwitcher(QWidget):
    """Combo box that asks the controller to switch the app language."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(t("gui.language")))

        self.combo = QComboBox()
        for code, name in LANGUAGE_NAMES.items():
            self.combo.addItem(name, code)
        self.combo.setCurrentIndex(self.combo.findData(get_locale()))
        # `activated` fires only on user choice (not on programmatic changes).
        self.combo.activated.connect(
            lambda _index: controller.change_language(self.combo.currentData())
        )
        layout.addWidget(self.combo)