"""
Update banner (task plan Phase 5: "check on startup, prompt to restart, never
interrupt an active transaction"). Lives on the LOGIN screen only, so nobody is
mid-transaction when an update is offered or applied.

- The check runs in a background QThread; failures (offline clinic, GitHub down)
  are logged and otherwise invisible.
- "Update now" downloads + verifies (checksum AND signature) in a thread with a
  progress bar, then asks the controller to start the helper and quit.
- Only active in the installed (frozen) build with the repo/key configured.
"""

import logging
import shutil

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from i18n import t
from updater.apply import can_self_update
from updater.checksum import VerificationError
from updater.downloader import DownloadError, new_staging_dir
from updater.service import download_verified_update
from updater.version_check import UpdateCheckError, check_for_update

log = logging.getLogger(__name__)

# Running threads must stay referenced until they finish, even if the login
# screen that started them was rebuilt (e.g. a language switch).
_ACTIVE: set = set()
# One network check per process; later login screens reuse the answer.
_cache = {"checked": False, "release": None}


def _remember(release) -> None:
    _cache["checked"] = True
    _cache["release"] = release


class _CheckThread(QThread):
    result = Signal(object)  # ReleaseInfo or None

    def run(self):
        try:
            self.result.emit(check_for_update())
        except UpdateCheckError as exc:
            log.info("Update check failed (ignored): %s", exc)
        except Exception:
            log.exception("Unexpected error during update check (ignored)")


class _DownloadThread(QThread):
    progress = Signal(int, int)
    done = Signal(object)  # Path of the verified exe
    failed = Signal(str)  # "download" | "verify"

    def __init__(self, release):
        super().__init__()
        self._release = release

    def run(self):
        staging = new_staging_dir()
        try:
            path = download_verified_update(
                self._release, staging, progress=lambda r, total: self.progress.emit(r, total)
            )
        except VerificationError:
            log.error("Update failed verification and was discarded", exc_info=True)
            shutil.rmtree(staging, ignore_errors=True)
            self.failed.emit("verify")
        except DownloadError:
            log.warning("Update download failed", exc_info=True)
            shutil.rmtree(staging, ignore_errors=True)
            self.failed.emit("download")
        except Exception:
            log.exception("Unexpected error while downloading update")
            shutil.rmtree(staging, ignore_errors=True)
            self.failed.emit("download")
        else:
            self.done.emit(path)


def _track(thread: QThread) -> None:
    _ACTIVE.add(thread)
    thread.finished.connect(lambda: _ACTIVE.discard(thread))


class UpdateBanner(QFrame):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._release = None
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.label = QLabel()
        self.label.setWordWrap(True)
        self.button = QPushButton(t("gui.update.button"))
        self.button.clicked.connect(self._start_download)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setVisible(False)

        row = QHBoxLayout()
        row.addWidget(self.label, 1)
        row.addWidget(self.button)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.progress)
        layout.addWidget(self.error_label)

        self.setVisible(False)
        if not can_self_update():
            return
        if _cache["checked"]:
            self._show(_cache["release"])
        else:
            thread = _CheckThread()
            _track(thread)
            thread.result.connect(_remember)  # module function: survives this widget
            thread.result.connect(self._on_checked)
            thread.start()

    def _on_checked(self, release) -> None:
        self._show(release)

    def _show(self, release) -> None:
        if release is None:
            return
        self._release = release
        self.label.setText(t("gui.update.available", version=str(release.version)))
        self.setVisible(True)

    def _start_download(self) -> None:
        if self._release is None:
            return
        self.button.setEnabled(False)
        self.error_label.setVisible(False)
        self.label.setText(t("gui.update.downloading"))
        self.progress.setValue(0)
        self.progress.setVisible(True)

        thread = _DownloadThread(self._release)
        _track(thread)
        thread.progress.connect(self._on_progress)
        thread.done.connect(self._on_downloaded)
        thread.failed.connect(self._on_failed)
        thread.start()

    def _on_progress(self, received: int, total: int) -> None:
        if total:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(received * 100 / total))
        else:
            self.progress.setRange(0, 0)  # busy indicator: size unknown

    def _on_downloaded(self, path) -> None:
        self.label.setText(t("gui.update.restarting"))
        self.progress.setRange(0, 0)
        if not self.controller.apply_update(path):
            self._on_failed("apply")

    def _on_failed(self, kind: str) -> None:
        self.progress.setVisible(False)
        self.label.setText(t("gui.update.available", version=str(self._release.version)))
        self.error_label.setText(t(f"gui.update.failed_{kind}"))
        self.error_label.setVisible(True)
        self.button.setEnabled(True)
