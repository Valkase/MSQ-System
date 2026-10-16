"""
Thin wrappers around pg_dump, pg_restore and createdb.

The database password is passed through the PGPASSWORD environment variable,
never on the command line, so it can't appear in a process list or a log.
"""

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from backup.errors import BackupError

_CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class ConnectionSettings:
    host: str | None
    port: int | None
    user: str | None
    password: str | None
    database: str | None

    @classmethod
    def from_config(cls) -> "ConnectionSettings":
        import config

        return cls(
            host=config.DB_HOST,
            port=int(config.DB_PORT) if config.DB_PORT else None,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
        )

    @classmethod
    def from_url(cls, url: str) -> "ConnectionSettings":
        u = make_url(url)
        return cls(u.host, u.port, u.username, u.password, u.database)

    def sqlalchemy_url(self, database: str | None = None) -> URL:
        return URL.create(
            "postgresql+psycopg2",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=database or self.database,
        )


def find_pg_tool(name: str) -> str:
    """Locate a PostgreSQL client tool: PG_BIN_DIR, then PATH, then the default Windows install."""
    windows = sys.platform.startswith("win")
    exe = name + (".exe" if windows else "")

    pg_bin = os.getenv("PG_BIN_DIR")
    if pg_bin and (Path(pg_bin) / exe).is_file():
        return str(Path(pg_bin) / exe)

    found = shutil.which(name)
    if found:
        return found

    if windows:
        matches = glob.glob(rf"C:\Program Files\PostgreSQL\*\bin\{exe}")

        def major(path: str) -> int:
            try:
                return int(Path(path).parent.parent.name)
            except ValueError:
                return 0

        if matches:
            return sorted(matches, key=major, reverse=True)[0]

    raise BackupError(
        f"Could not find {exe}. Install the PostgreSQL client tools or set PG_BIN_DIR in .env."
    )


def _host_args(conn: ConnectionSettings) -> list[str]:
    args: list[str] = []
    if conn.host:
        args += ["--host", conn.host]
    if conn.port:
        args += ["--port", str(conn.port)]
    if conn.user:
        args += ["--username", conn.user]
    return args


def pg_dump_command(exe: str, dest: Path, conn: ConnectionSettings) -> list[str]:
    return [
        exe,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--no-password",
        "--file", str(dest),
        *_host_args(conn),
        "--dbname", str(conn.database),
    ]


def pg_restore_command(
    exe: str, backup_file: Path, conn: ConnectionSettings, *, replace: bool
) -> list[str]:
    args = [exe, "--single-transaction", "--exit-on-error", "--no-owner", "--no-privileges", "--no-password"]
    if replace:
        args += ["--clean", "--if-exists"]
    args += _host_args(conn)
    args += ["--dbname", str(conn.database), str(backup_file)]
    return args


def createdb_command(exe: str, conn: ConnectionSettings) -> list[str]:
    return [exe, "--no-password", *_host_args(conn), str(conn.database)]


def build_env(conn: ConnectionSettings) -> dict:
    env = os.environ.copy()
    if conn.password:
        env["PGPASSWORD"] = conn.password
    env["PGCONNECT_TIMEOUT"] = "10"
    return env


def run_tool(args: list[str], conn: ConnectionSettings, *, runner=subprocess.run, timeout: float = 1800) -> None:
    """Run a PostgreSQL tool; raise BackupError (with its stderr tail) on any failure."""
    tool = Path(args[0]).stem
    kwargs = {"env": build_env(conn), "capture_output": True, "text": True, "timeout": timeout}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = _CREATE_NO_WINDOW  # no console flash from the windowed exe
    try:
        result = runner(args, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"{tool} timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise BackupError(f"Could not run {tool}: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip()[-500:]
        raise BackupError(f"{tool} failed (exit code {result.returncode}): {tail}")


def dump_database(
    dest: Path,
    conn: ConnectionSettings | None = None,
    *,
    runner=subprocess.run,
    find_tool=find_pg_tool,
    timeout: float = 1800,
) -> None:
    """pg_dump the database to `dest` (custom format). A partial file is removed on failure."""
    conn = conn or ConnectionSettings.from_config()
    try:
        run_tool(pg_dump_command(find_tool("pg_dump"), dest, conn), conn, runner=runner, timeout=timeout)
    except BackupError:
        try:
            Path(dest).unlink(missing_ok=True)
        except OSError:
            pass
        raise