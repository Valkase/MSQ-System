"""setup_tool pieces that don't need Windows services or PostgreSQL."""

import pytest

import setup_tool


@pytest.fixture(autouse=True)
def _programdata(tmp_path, monkeypatch):
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setattr(setup_tool, "_run", lambda *a, **k: None)  # skip icacls


def test_env_file_has_local_settings_and_auto_migrate():
    path = setup_tool.write_env("s3cret_pw-1")
    text = path.read_text(encoding="utf-8")
    assert "DB_HOST=localhost" in text
    assert f"DB_PORT={setup_tool.PG_PORT}" in text
    assert "DB_PASSWORD=s3cret_pw-1" in text
    assert "AUTO_MIGRATE=1" in text
    assert "BACKUP_DRIVE_PATHS" not in text


def test_existing_env_password_is_reused():
    setup_tool.write_env("keep-me")
    assert setup_tool.read_env_value("DB_PASSWORD") == "keep-me"


def test_creds_file_is_read_with_bom_and_deleted(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_bytes(b"\xef\xbb\xbfadmin\r\nPass word 123\r\n")
    assert setup_tool.read_creds(f) == ("admin", "Pass word 123")
    assert not f.exists()


def test_incomplete_creds_are_rejected(tmp_path):
    f = tmp_path / "creds.txt"
    f.write_text("admin\n", encoding="utf-8")
    with pytest.raises(setup_tool.SetupError):
        setup_tool.read_creds(f)


def test_generated_secrets_are_long_and_unique():
    a, b = setup_tool.new_secret(), setup_tool.new_secret()
    assert len(a) >= 30 and a != b