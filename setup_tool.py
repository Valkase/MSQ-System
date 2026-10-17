"""
First-install / upgrade helper, run by the installer as:

    HealthCenterSystem.exe --setup --pg-installer <exe> [--creds <file>]

Steps (each safe to repeat): install a private PostgreSQL service, create the
app role + database, write .env, build the tables, create the first admin,
schedule the backups. Progress goes to setup.log; passwords are never logged.
"""

import argparse
import logging
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from app_paths import APP_DIR_NAME, shared_config_dir

SERVICE_NAME = "HealthCenterPostgres"
PG_PORT = 54329
DB_NAME = "healthcenter"
DB_USER = "hcs_app"
TASK_NAME = "HealthCenterBackup"
USERS_SID = "*S-1-5-32-545"
ADMINS_SID = "*S-1-5-32-544"
SYSTEM_SID = "*S-1-5-18"

log = logging.getLogger("setup")


class SetupError(Exception):
    pass


# --- locations -----------------------------------------------------------------


def config_folder() -> Path:
    return shared_config_dir()


def pg_root() -> Path:
    return shared_config_dir().parent / "HealthCenterPG"


def pg_data_dir() -> Path:
    return pg_root() / "data"


def pg_secret_file() -> Path:
    return pg_root() / "superuser.txt"


def pg_prefix() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "HealthCenter" / "PostgreSQL"


# --- small helpers ---------------------------------------------------------------


def _run(args: list[str], *, timeout: float = 120, check: bool = True) -> subprocess.CompletedProcess:
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # no console window
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, creationflags=flags
    )
    if check and result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-400:]
        raise SetupError(f"{Path(args[0]).name} failed (exit {result.returncode}): {tail}")
    return result


def new_secret() -> str:
    return secrets.token_urlsafe(24)  # letters, digits, '-' and '_' only: safe in .env and URLs


def read_creds(path: Path) -> tuple[str, str]:
    """Two lines: username, password. The file is deleted straight after reading."""
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    finally:
        Path(path).unlink(missing_ok=True)
    if len(lines) < 2 or not lines[0].strip() or not lines[1]:
        raise SetupError("Administrator credentials are missing")
    return lines[0].strip(), lines[1]


def service_exists() -> bool:
    return _run(["sc", "query", SERVICE_NAME], check=False).returncode == 0


def read_env_value(key: str) -> str | None:
    env = config_folder() / ".env"
    if not env.is_file():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def write_env(app_secret: str) -> Path:
    folder = config_folder()
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "DB_HOST=localhost",
        f"DB_PORT={PG_PORT}",
        f"DB_NAME={DB_NAME}",
        f"DB_USER={DB_USER}",
        f"DB_PASSWORD={app_secret}",
        f"PG_BIN_DIR={pg_prefix() / 'bin'}",
        "AUTO_MIGRATE=1",
    ]
    path = folder / ".env"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run(["icacls", str(folder), "/grant", f"{USERS_SID}:(OI)(CI)M"], check=False)
    return path


# --- PostgreSQL ----------------------------------------------------------------


def install_postgres(installer: Path) -> str:
    """Silent install of a private PostgreSQL service. Returns the superuser secret."""
    if service_exists():
        if pg_secret_file().is_file():
            log.info("PostgreSQL service already present; reusing it")
            return pg_secret_file().read_text(encoding="utf-8").strip()
        raise SetupError("PostgreSQL service exists but its admin secret file is missing")
    if not Path(installer).is_file():
        raise SetupError(f"PostgreSQL installer not found: {installer}")

    secret = new_secret()
    pg_root().mkdir(parents=True, exist_ok=True)
    pg_secret_file().write_text(secret, encoding="utf-8")
    _run(["icacls", str(pg_secret_file()), "/inheritance:r", "/grant:r",
          f"{ADMINS_SID}:F", f"{SYSTEM_SID}:F"], check=False)

    log.info("Installing PostgreSQL (a few minutes)")
    _run(
        [
            str(installer), "--mode", "unattended", "--unattendedmodeui", "none",
            "--superpassword", secret, "--servicename", SERVICE_NAME,
            "--serverport", str(PG_PORT), "--prefix", str(pg_prefix()),
            "--datadir", str(pg_data_dir()),
            "--enable-components", "server,commandlinetools",
            "--disable-components", "pgAdmin,stackbuilder",
        ],
        timeout=1800,
    )
    return secret


def _connect_super(secret: str, timeout: float = 120):
    import psycopg2

    deadline = time.monotonic() + timeout
    while True:
        try:
            conn = psycopg2.connect(
                host="localhost", port=PG_PORT, user="postgres", password=secret,
                dbname="postgres", connect_timeout=3,
            )
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError:
            if time.monotonic() > deadline:
                raise SetupError("PostgreSQL did not start in time")
            time.sleep(2)


def provision_database(super_secret: str, app_secret: str) -> None:
    import psycopg2

    conn = _connect_super(super_secret)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (DB_USER,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(f"{verb} ROLE {DB_USER} LOGIN CREATEDB PASSWORD %s", (app_secret,))

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if not cur.fetchone():
            # UTF8 is required for Arabic text, whatever the Windows language is.
            for collation in ("English_United States.1252", "C"):
                try:
                    cur.execute(
                        f"CREATE DATABASE {DB_NAME} OWNER {DB_USER} ENCODING 'UTF8' "
                        f"TEMPLATE template0 LC_COLLATE '{collation}' LC_CTYPE '{collation}'"
                    )
                    break
                except psycopg2.Error:
                    log.warning("Collation %s rejected, trying the next", collation)
            else:
                raise SetupError("Could not create the database")
        cur.execute("ALTER SYSTEM SET listen_addresses = 'localhost'")  # this PC only
    finally:
        conn.close()

    _run(["net", "stop", SERVICE_NAME], check=False, timeout=180)
    _run(["net", "start", SERVICE_NAME], timeout=180)
    _connect_super(super_secret).close()


# --- schema, admin, backups ----------------------------------------------------


def _alembic_config():
    from alembic.config import Config

    from app_paths import resource_path

    cfg = Config()
    cfg.set_main_option("script_location", str(resource_path("migrations")))
    return cfg


def upgrade_database(*, pre_backup: bool = True) -> None:
    """Bring the database to the schema this build expects, saving a copy first."""
    from alembic import command

    if pre_backup:
        from backup.pgtools import dump_database

        folder = config_folder() / "pre-upgrade"
        folder.mkdir(parents=True, exist_ok=True)
        dump_database(folder / f"pre-upgrade-{datetime.now():%Y%m%d-%H%M%S}.dump")
        for old in sorted(folder.glob("pre-upgrade-*.dump"), reverse=True)[5:]:
            old.unlink(missing_ok=True)
    command.upgrade(_alembic_config(), "head")


def create_admin(username: str, secret: str) -> bool:
    """Create the first admin unless one exists. Returns True if created."""
    from argon2 import PasswordHasher

    from data.database import SessionLocal
    from data.models.user import ROLE_ADMIN, User
    from logic.validation import validate_password

    with SessionLocal() as session:
        if session.query(User).filter(User.role == ROLE_ADMIN).first():
            return False
        session.add(
            User(
                username=username,
                password_hash=PasswordHasher().hash(validate_password(secret)),
                role=ROLE_ADMIN,
                active=True,
            )
        )
        session.commit()
    return True


def register_backup_task(exe: Path) -> None:
    _run(
        [
            "schtasks", "/Create", "/TN", TASK_NAME, "/TR", f'"{exe}" --backup',
            "/SC", "HOURLY", "/MO", "1", "/RU", "SYSTEM", "/RL", "HIGHEST", "/F",
        ]
    )


# --- entry point -----------------------------------------------------------------


def run_setup(pg_installer: Path, creds: Path | None) -> None:
    admin = read_creds(creds) if creds else None

    super_secret = install_postgres(pg_installer)
    app_secret = read_env_value("DB_PASSWORD") or new_secret()
    provision_database(super_secret, app_secret)
    write_env(app_secret)  # before the app modules below read their settings

    log.info("Building the database tables")
    upgrade_database(pre_backup=False)

    if admin:
        if create_admin(*admin):
            log.info("First administrator created")
        else:
            log.info("An administrator already exists; not creating another")

    register_backup_task(Path(sys.executable).resolve())
    (config_folder() / "setup_complete.txt").write_text("ok", encoding="utf-8")
    log.info("Setup finished")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-installer", type=Path, required=True)
    parser.add_argument("--creds", type=Path)
    args = parser.parse_args(argv)

    folder = config_folder()
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        filename=folder / "setup.log",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        run_setup(args.pg_installer, args.creds)
    except Exception:
        log.exception("Setup failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())