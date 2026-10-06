"""
Download helpers (task plan Phase 5). Files are streamed to "<name>.part" and
only renamed into place when complete, so a dropped connection can never leave
something that looks like a finished download. Size is capped, and a body that
doesn't match Content-Length is rejected.
"""

import os
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import requests

from updater import settings


STAGING_PREFIX = "hcs-update-"


class DownloadError(Exception):
    """A download failed, was truncated, or exceeded the size cap."""


def new_staging_dir() -> Path:
    """A fresh temp folder for one update attempt (never the install folder)."""
    return Path(tempfile.mkdtemp(prefix=STAGING_PREFIX))


def _stream(
    url: str, *, http_get, timeout: float, chunk_size: int, max_bytes: int
) -> Iterator[tuple[bytes, int, int]]:
    try:
        response = http_get(
            url, stream=True, timeout=timeout, headers={"User-Agent": settings.USER_AGENT}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DownloadError(f"Download failed: {exc}") from exc

    try:
        total = int(response.headers.get("Content-Length") or 0)
        if total > max_bytes:
            raise DownloadError("File is larger than the allowed maximum")
        received = 0
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                raise DownloadError("File is larger than the allowed maximum")
            yield chunk, received, total
        if total and received != total:
            raise DownloadError("Download was truncated")
    except requests.RequestException as exc:
        raise DownloadError(f"Download interrupted: {exc}") from exc
    finally:
        close = getattr(response, "close", None)
        if close:
            close()


def download_bytes(
    url: str,
    *,
    http_get=requests.get,
    timeout: float = settings.DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = settings.MAX_SMALL_FILE_BYTES,
) -> bytes:
    """For tiny files (checksum, signature)."""
    parts = [
        chunk
        for chunk, _r, _t in _stream(
            url, http_get=http_get, timeout=timeout, chunk_size=8192, max_bytes=max_bytes
        )
    ]
    return b"".join(parts)


def download_file(
    url: str,
    dest: Path,
    *,
    http_get=requests.get,
    timeout: float = settings.DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = settings.MAX_EXE_BYTES,
    chunk_size: int = 1024 * 1024,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """
    Stream `url` to `dest`. `progress(received, total)` is called per chunk
    (total is 0 if the server didn't send Content-Length). On any failure the
    partial file is removed and DownloadError is raised.
    """
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as fh:
            for chunk, received, total in _stream(
                url, http_get=http_get, timeout=timeout, chunk_size=chunk_size, max_bytes=max_bytes
            ):
                fh.write(chunk)
                if progress:
                    progress(received, total)
        os.replace(part, dest)
    except DownloadError:
        part.unlink(missing_ok=True)
        raise
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"Could not write download: {exc}") from exc
    return dest
