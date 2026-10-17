"""Start-menu tool: mark a flash drive as the backup drive (no command line needed)."""

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from backup.drives import initialize_drive
from backup.errors import BackupError
from i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, set_locale, t


def run() -> int:
    app = QApplication(sys.argv)
    code = str(QSettings("HealthCenter", "HealthCenterSystem").value("locale", DEFAULT_LOCALE))
    if code not in SUPPORTED_LOCALES:
        code = DEFAULT_LOCALE
    set_locale(code)
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if code == "ar" else Qt.LayoutDirection.LeftToRight
    )

    chosen = QFileDialog.getExistingDirectory(None, t("gui.drive.pick_title"))
    if not chosen:
        return 0
    root = Path(chosen)
    if root != Path(root.anchor):
        QMessageBox.warning(None, t("gui.app_title"), t("gui.drive.not_root"))
        return 1
    try:
        drive = initialize_drive(root)
    except BackupError as exc:
        QMessageBox.warning(None, t("gui.app_title"), t("gui.drive.failed", error=str(exc)))
        return 1
    QMessageBox.information(
        None, t("gui.app_title"), t("gui.drive.done", drive=str(drive.root))
    )
    return 0