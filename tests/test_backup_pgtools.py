"""pg_dump / pg_restore wrappers: no password on the command line, clean failures."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backup import pgtools
from backup.errors import BackupError
from backup.pgtools import ConnectionSettings

CONN = ConnectionSettings("db-host", 5432, "hcs_app", "s3cret-pw", "healthcenter")


class Recorder:
    def __init__(self, returncode=0, stderr="", side_effect=None):
        self.calls, self.returncode, self.stderr, self.side_effect = [], returncode, stderr, side_effect

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.side_effect:
            self.side_effect(args)
        return SimpleNamespace(returncode=self.returncode, stderr=self.stderr)


def test_commands_never_contain_the_password():
    commands = [
        pgtools.pg_dump_command("pg_dump", Path("x.dump"), CONN),
        pgtools.pg_restore_command("pg_restore", Path("x.dump"), CONN, replace=True),
        pgtools.createdb_command("createdb", CONN),
    ]
    for args in commands:
        assert "s3cret-pw" not in " ".join(args)
        assert "--no-password" in args


def test_pg_dump_command_shape():
    args = pgtools.pg_dump_command("pg_dump", Path("x.dump"), CONN)
    assert "--format=custom" in args
    assert args[args.index("--dbname") + 1] == "healthcenter"
    assert args[args.index("--host") + 1] == "db-host"


def test_restore_command_is_a_single_transaction_and_replace_adds_clean():
    plain = pgtools.pg_restore_command("pg_restore", Path("x.dump"), CONN, replace=False)
    replace = pgtools.pg_restore_command("pg_restore", Path("x.dump"), CONN, replace=True)
    assert "--single-transaction" in plain and "--clean" not in plain
    assert "--clean" in replace and "--if-exists" in replace


def test_password_is_passed_through_the_environment_only():
    recorder = Recorder()
    pgtools.run_tool(["pg_dump"], CONN, runner=recorder)
    args, kwargs = recorder.calls[0]
    assert kwargs["env"]["PGPASSWORD"] == "s3cret-pw"
    assert "s3cret-pw" not in " ".join(args)


def test_a_failing_tool_raises_with_its_error_text():
    with pytest.raises(BackupError, match="connection refused"):
        pgtools.run_tool(["pg_dump"], CONN, runner=Recorder(2, "FATAL: connection refused"))


def test_a_missing_tool_raises_backup_error():
    def boom(args, **kw):
        raise FileNotFoundError("no such file")

    with pytest.raises(BackupError):
        pgtools.run_tool(["nope"], CONN, runner=boom)


def test_dump_database_removes_a_partial_file_on_failure(tmp_path):
    dest = tmp_path / "x.dump"
    recorder = Recorder(1, "disk full", side_effect=lambda args: dest.write_bytes(b"partial"))

    with pytest.raises(BackupError):
        pgtools.dump_database(dest, CONN, runner=recorder, find_tool=lambda n: n)

    assert not dest.exists()


def test_find_pg_tool_honours_pg_bin_dir(tmp_path, monkeypatch):
    exe = "pg_dump.exe" if sys.platform.startswith("win") else "pg_dump"
    (tmp_path / exe).write_text("")
    monkeypatch.setenv("PG_BIN_DIR", str(tmp_path))
    assert pgtools.find_pg_tool("pg_dump") == str(tmp_path / exe)