"""
Version check (task plan Phase 5): ask the GitHub Releases API for the latest
release and decide whether it is newer than the running version.

Errors raised here are for logs/developers; the GUI shows its own localized
message (or stays silent: the clinic may simply be offline).

A release is only offered if it carries all three assets (exe, .sha256, .sig)
and every download URL points into this repository's own release downloads.
"""

from dataclasses import dataclass

import requests
from packaging.version import InvalidVersion, Version

from updater import settings
from version import __version__


class UpdateCheckError(Exception):
    """The check failed or the release is malformed/untrusted."""


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    version: Version
    notes: str
    exe_url: str
    checksum_url: str
    signature_url: str


def parse_tag(tag: str) -> Version:
    cleaned = (tag or "").strip()
    if cleaned[:1] in ("v", "V"):
        cleaned = cleaned[1:]
    try:
        return Version(cleaned)
    except InvalidVersion as exc:
        raise UpdateCheckError(f"Unparseable release tag: {tag!r}") from exc


def _trusted_prefix(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/"


def check_for_update(
    current_version: str = __version__,
    *,
    owner: str = settings.GITHUB_OWNER,
    repo: str = settings.GITHUB_REPO,
    http_get=requests.get,
    timeout: float = settings.CHECK_TIMEOUT_SECONDS,
) -> ReleaseInfo | None:
    """
    Return a ReleaseInfo if a newer, complete release exists, else None.
    Raises UpdateCheckError on network failure or a malformed release.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": settings.USER_AGENT,
    }
    try:
        response = http_get(url, headers=headers, timeout=timeout)
        if response.status_code == 404:  # repository has no releases yet
            return None
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpdateCheckError(f"Could not query GitHub releases: {exc}") from exc

    if not isinstance(data, dict):
        raise UpdateCheckError("Unexpected response from GitHub releases API")
    if data.get("draft") or data.get("prerelease"):
        return None

    tag = data.get("tag_name") or ""
    latest = parse_tag(tag)
    if latest.is_prerelease or latest <= parse_tag(current_version):
        return None

    try:
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    except (KeyError, TypeError) as exc:
        raise UpdateCheckError("Malformed asset list in release") from exc

    wanted = (
        settings.APP_EXE_NAME,
        settings.CHECKSUM_ASSET_NAME,
        settings.SIGNATURE_ASSET_NAME,
    )
    missing = [name for name in wanted if name not in assets]
    if missing:
        raise UpdateCheckError(f"Release {tag} is missing assets: {', '.join(missing)}")

    prefix = _trusted_prefix(owner, repo)
    for name in wanted:
        if not str(assets[name]).startswith(prefix):
            raise UpdateCheckError(f"Untrusted download URL for {name}")

    return ReleaseInfo(
        tag=tag,
        version=latest,
        notes=data.get("body") or "",
        exe_url=assets[settings.APP_EXE_NAME],
        checksum_url=assets[settings.CHECKSUM_ASSET_NAME],
        signature_url=assets[settings.SIGNATURE_ASSET_NAME],
    )
