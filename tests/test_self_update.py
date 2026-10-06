"""
Tests for updater/ (task plan Phase 5 + Phase 6's self-update items): version
check, download, checksum + Ed25519 signature verification, and the combined
download_verified_update flow. All HTTP is faked; nothing touches the network.
"""

import hashlib

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from updater import settings
from updater.checksum import (
    ChecksumError,
    SignatureError,
    parse_checksum_file,
    signing_message,
    verify_release_file,
)
from updater.downloader import DownloadError, download_file
from updater.service import download_verified_update
from updater.version_check import ReleaseInfo, UpdateCheckError, check_for_update, parse_tag

OWNER, REPO = "acme", "clinic"
EXE = settings.APP_EXE_NAME
EXE_BYTES = b"MZ" + b"fake-exe-payload" * 5000


# --- fakes ---------------------------------------------------------------------


class FakeResponse:
    def __init__(self, *, json_data=None, content=b"", status=200, headers=None, fail_after=None):
        self._json, self._content, self.status_code = json_data, content, status
        self.headers = headers if headers is not None else {"Content-Length": str(len(content))}
        self._fail_after = fail_after

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._json

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._content), chunk_size):
            if self._fail_after is not None and i >= self._fail_after:
                raise requests.ConnectionError("dropped")
            yield self._content[i : i + chunk_size]

    def close(self):
        pass


def router(routes):
    def http_get(url, **_kwargs):
        if url not in routes:
            raise requests.ConnectionError(f"no route for {url}")
        return routes[url]

    return http_get


def new_key():
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    return private, public_hex


def sign(private, tag, content):
    digest = hashlib.sha256(content).hexdigest()
    return digest, private.sign(signing_message(tag, digest))


def base_url(tag):
    return f"https://github.com/{OWNER}/{REPO}/releases/download/{tag}/"


def release_json(tag="v1.2.0", names=None, **extra):
    names = names or [EXE, settings.CHECKSUM_ASSET_NAME, settings.SIGNATURE_ASSET_NAME]
    data = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "body": "notes",
        "assets": [{"name": n, "browser_download_url": base_url(tag) + n} for n in names],
    }
    data.update(extra)
    return data


API = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"


def check(data=None, current="1.0.0", status=200):
    http = router({API: FakeResponse(json_data=data, status=status)})
    return check_for_update(current, owner=OWNER, repo=REPO, http_get=http)


# --- version check ---------------------------------------------------------------


def test_newer_release_is_returned_with_all_urls():
    info = check(release_json())
    assert isinstance(info, ReleaseInfo)
    assert info.tag == "v1.2.0"
    assert info.exe_url == base_url("v1.2.0") + EXE
    assert info.signature_url.endswith(settings.SIGNATURE_ASSET_NAME)


@pytest.mark.parametrize("current", ["1.2.0", "1.3.0"])
def test_same_or_older_release_is_not_offered(current):
    assert check(release_json(), current=current) is None


def test_versions_compare_numerically_not_as_strings():
    assert check(release_json("v1.10.0"), current="1.9.0") is not None


def test_tag_without_v_prefix_works():
    assert check(release_json("1.2.0")) is not None


def test_no_releases_yet_is_not_an_error():
    assert check({}, status=404) is None


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_draft_and_prerelease_are_ignored(flag):
    assert check(release_json(**{flag: True})) is None


def test_release_missing_signature_is_rejected():
    names = [EXE, settings.CHECKSUM_ASSET_NAME]
    with pytest.raises(UpdateCheckError):
        check(release_json(names=names))


def test_download_url_outside_the_repo_is_rejected():
    data = release_json()
    data["assets"][0]["browser_download_url"] = "https://evil.example.com/" + EXE
    with pytest.raises(UpdateCheckError):
        check(data)


def test_network_failure_raises_update_check_error():
    def boom(url, **_kw):
        raise requests.ConnectionError("offline")

    with pytest.raises(UpdateCheckError):
        check_for_update("1.0.0", owner=OWNER, repo=REPO, http_get=boom)


def test_server_error_raises_update_check_error():
    with pytest.raises(UpdateCheckError):
        check({}, status=500)


def test_garbage_tag_raises():
    with pytest.raises(UpdateCheckError):
        parse_tag("release-final")


# --- downloader -------------------------------------------------------------------


def test_download_file_writes_content_and_reports_progress(tmp_path):
    seen = []
    http = router({"u": FakeResponse(content=EXE_BYTES)})

    dest = download_file(
        "u", tmp_path / "a.exe", http_get=http, chunk_size=4096, progress=lambda r, t: seen.append((r, t))
    )

    assert dest.read_bytes() == EXE_BYTES
    assert seen[-1] == (len(EXE_BYTES), len(EXE_BYTES))
    assert not (tmp_path / "a.exe.part").exists()


def test_oversized_download_is_rejected_and_cleaned_up(tmp_path):
    http = router({"u": FakeResponse(content=EXE_BYTES)})
    with pytest.raises(DownloadError):
        download_file("u", tmp_path / "a.exe", http_get=http, max_bytes=1000)
    assert list(tmp_path.iterdir()) == []


def test_truncated_download_is_rejected_and_cleaned_up(tmp_path):
    resp = FakeResponse(content=EXE_BYTES, headers={"Content-Length": str(len(EXE_BYTES) + 10)})
    with pytest.raises(DownloadError):
        download_file("u", tmp_path / "a.exe", http_get=router({"u": resp}))
    assert list(tmp_path.iterdir()) == []


def test_connection_dropped_mid_download_leaves_nothing_behind(tmp_path):
    resp = FakeResponse(content=EXE_BYTES, fail_after=8192)
    with pytest.raises(DownloadError):
        download_file("u", tmp_path / "a.exe", http_get=router({"u": resp}), chunk_size=4096)
    assert list(tmp_path.iterdir()) == []


# --- checksum / signature ---------------------------------------------------------


def _exe_file(tmp_path, content=EXE_BYTES):
    path = tmp_path / EXE
    path.write_bytes(content)
    return path


def test_valid_checksum_and_signature_pass(tmp_path):
    private, public_hex = new_key()
    digest, sig = sign(private, "v1.2.0", EXE_BYTES)
    verify_release_file(_exe_file(tmp_path), "v1.2.0", f"{digest}  {EXE}\n", sig, public_hex)


def test_tampered_file_fails_checksum(tmp_path):
    private, public_hex = new_key()
    digest, sig = sign(private, "v1.2.0", EXE_BYTES)
    path = _exe_file(tmp_path, EXE_BYTES + b"malware")
    with pytest.raises(ChecksumError):
        verify_release_file(path, "v1.2.0", digest, sig, public_hex)


def test_attacker_replacing_exe_and_checksum_still_fails_signature(tmp_path):
    _owner_key, owner_public = new_key()
    attacker_key, _ = new_key()
    evil = b"MZ-evil"
    digest, sig = sign(attacker_key, "v1.2.0", evil)  # self-consistent, signed with the wrong key
    with pytest.raises(SignatureError):
        verify_release_file(_exe_file(tmp_path, evil), "v1.2.0", digest, sig, owner_public)


def test_signature_cannot_be_replayed_onto_another_tag(tmp_path):
    private, public_hex = new_key()
    digest, sig = sign(private, "v1.0.1", EXE_BYTES)
    with pytest.raises(SignatureError):
        verify_release_file(_exe_file(tmp_path), "v9.9.9", digest, sig, public_hex)


def test_missing_public_key_refuses_to_install(tmp_path):
    private, _ = new_key()
    digest, sig = sign(private, "v1.2.0", EXE_BYTES)
    with pytest.raises(SignatureError):
        verify_release_file(_exe_file(tmp_path), "v1.2.0", digest, sig, "")


@pytest.mark.parametrize("text", ["", "not-a-digest", "abc123  file.exe"])
def test_malformed_checksum_file_is_rejected(text):
    with pytest.raises(ChecksumError):
        parse_checksum_file(text)


def test_checksum_file_formats():
    digest = hashlib.sha256(b"x").hexdigest()
    assert parse_checksum_file(digest) == digest
    assert parse_checksum_file(f"{digest.upper()}  {EXE}\n") == digest


# --- full flow --------------------------------------------------------------------


def _release_and_routes(private, tamper=False):
    tag = "v1.2.0"
    digest, sig = sign(private, tag, EXE_BYTES)
    served = EXE_BYTES + b"x" if tamper else EXE_BYTES
    release = ReleaseInfo(
        tag=tag,
        version=parse_tag(tag),
        notes="",
        exe_url=base_url(tag) + EXE,
        checksum_url=base_url(tag) + settings.CHECKSUM_ASSET_NAME,
        signature_url=base_url(tag) + settings.SIGNATURE_ASSET_NAME,
    )
    routes = {
        release.exe_url: FakeResponse(content=served),
        release.checksum_url: FakeResponse(content=f"{digest}  {EXE}\n".encode()),
        release.signature_url: FakeResponse(content=sig),
    }
    return release, router(routes)


def test_download_verified_update_returns_the_verified_exe(tmp_path):
    private, public_hex = new_key()
    release, http = _release_and_routes(private)

    path = download_verified_update(release, tmp_path, public_key_hex=public_hex, http_get=http)

    assert path == tmp_path / EXE
    assert path.read_bytes() == EXE_BYTES


def test_download_verified_update_deletes_a_tampered_file(tmp_path):
    private, public_hex = new_key()
    release, http = _release_and_routes(private, tamper=True)

    with pytest.raises(ChecksumError):
        download_verified_update(release, tmp_path, public_key_hex=public_hex, http_get=http)

    assert list(tmp_path.iterdir()) == []
