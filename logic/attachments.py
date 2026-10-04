"""
Attachment opening (task plan 2.1: "Open an attachment — resolve the stored
path and launch it in the OS's default viewer; handle the case where the
path no longer resolves").

Creating/listing attachments lives in logic/patients.py. This module only
handles opening. `launcher` is injectable so tests never start a real viewer.

Because the DB stores a path, not the file, a file attached at one desk
only opens at another if the path resolves there too (shared-folder
convention is still an open decision in the task plan). When it doesn't,
the user gets a clear AttachmentNotFoundError message, never a crash.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from data.models.attachment import Attachment
from i18n import t
from logic.errors import AttachmentNotFoundError, AttachmentOpenError, NotFoundError


def get_attachment(session: Session, attachment_id: uuid.UUID) -> Attachment:
    attachment = session.get(Attachment, attachment_id)
    if attachment is None:
        raise NotFoundError(t("attachments.not_found", attachment_id=attachment_id))
    return attachment


def _launch_default(path: Path) -> None:
    """Open `path` in the operating system's default application."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_attachment(
    session: Session,
    attachment_id: uuid.UUID,
    *,
    launcher: Callable[[Path], None] = _launch_default,
) -> None:
    """
    Resolve the stored path and open it. Raises AttachmentNotFoundError if
    the path doesn't point to an existing file from THIS computer, and
    AttachmentOpenError if the OS refuses to open it.
    """
    attachment = get_attachment(session, attachment_id)
    path = Path(attachment.file_path)

    try:
        exists = path.is_file()
    except OSError:  # e.g. unreachable network share
        exists = False
    if not exists:
        raise AttachmentNotFoundError(
            t("attachments.file_missing", file_path=attachment.file_path)
        )

    try:
        launcher(path)
    except OSError as exc:
        raise AttachmentOpenError(
            t("attachments.open_failed", file_path=attachment.file_path)
        ) from exc