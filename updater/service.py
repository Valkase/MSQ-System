"""
High-level entry points the GUI will call (task plan Phase 5). Nothing here
touches the installed exe: it only finds a release and produces a downloaded,
fully VERIFIED file in a staging folder. Applying it is the separate updater
helper's job (it must run after the main app has closed).
"""

from collections.abc import Callable
from pathlib import Path

import requests

from updater import settings
from updater.checksum import VerificationError, verify_release_file
from updater.downloader import download_bytes, download_file
from updater.version_check import ReleaseInfo


def download_verified_update(
    release: ReleaseInfo,
    staging_dir: Path,
    *,
    public_key_hex: str = settings.SIGNING_PUBLIC_KEY_HEX,
    http_get=requests.get,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """
    Download the release exe into `staging_dir` and verify checksum + signature.
    Returns the path of the verified exe. If verification fails the file is
    deleted and the VerificationError propagates (never install in that case).
    """
    # Small files first so a bad release fails before the big download.
    checksum_text = download_bytes(release.checksum_url, http_get=http_get).decode(
        "utf-8", "replace"
    )
    signature = download_bytes(release.signature_url, http_get=http_get, max_bytes=1024)

    exe_path = Path(staging_dir) / settings.APP_EXE_NAME
    download_file(release.exe_url, exe_path, http_get=http_get, progress=progress)
    try:
        verify_release_file(exe_path, release.tag, checksum_text, signature, public_key_hex)
    except VerificationError:
        exe_path.unlink(missing_ok=True)
        raise
    return exe_path
