"""
Phase 6 "basic security pass": passwords never logged or displayed, SQL
stays parameterized, no floats in money code, secrets stay out of git.
Static checks parse the source with `ast`, so they also catch code added later.
"""

import ast
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from data.models.audit_log import AuditLog
from data.models.user import ROLE_RECEPTIONIST
from logic import auth
from logic.errors import ValidationError
from logic.validation import validate_password

ROOT = Path(__file__).resolve().parent.parent
APP_DIRS = ("logic", "gui", "data", "updater", "scripts", "backup")
FINANCIAL_FILES = ("logic/transactions.py", "logic/adjustments.py", "logic/reports.py")


def _app_files():
    files = [ROOT / n for n in ("main.py", "config.py", "app_paths.py", "version.py")]
    for folder in APP_DIRS:
        files += sorted((ROOT / folder).rglob("*.py"))
    return [f for f in files if f.exists()]


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# --- SQL stays parameterized -------------------------------------------------------


def _is_dynamic_string(node) -> bool:
    return (
        isinstance(node, (ast.JoinedStr, ast.BinOp))
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
        )
    )


def test_no_raw_sql_built_from_dynamic_strings():
    offenders = []
    for path in _app_files():
        for node in ast.walk(_parse(path)):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            is_sql_call = (isinstance(func, ast.Name) and name == "text") or (
                isinstance(func, ast.Attribute) and name in {"execute", "exec_driver_sql"}
            )
            if is_sql_call and _is_dynamic_string(node.args[0]):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == [], f"SQL built with f-string/%/+/.format: {offenders}"


# --- Decimal throughout in money code ----------------------------------------------


@pytest.mark.parametrize("relative", FINANCIAL_FILES)
def test_no_floats_in_financial_modules(relative):
    offenders = []
    for node in ast.walk(_parse(ROOT / relative)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(f"float literal at line {node.lineno}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
            offenders.append(f"float() at line {node.lineno}")
    assert offenders == []


# --- passwords are never logged or printed -----------------------------------------

_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def _mentions_password(node) -> bool:
    for child in ast.walk(node):
        ident = child.id if isinstance(child, ast.Name) else getattr(child, "attr", None)
        if isinstance(ident, str) and "password" in ident.lower():
            return True
    return False


def test_no_log_or_print_call_touches_a_password_variable():
    offenders = []
    for path in _app_files():
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_log = (isinstance(func, ast.Name) and func.id == "print") or (
                isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS
            )
            if not is_log:
                continue
            parts = list(node.args) + [kw.value for kw in node.keywords]
            if any(_mentions_password(p) for p in parts):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == [], f"password-like value passed to a log/print call: {offenders}"


# --- runtime: nothing sensitive leaks into audit rows, reprs or messages -----------

PASSWORD = "correct-horse-1"
NEW_PASSWORD = "brand-new-pass-2"
RESET_PASSWORD = "reset-by-admin-3"


@pytest.fixture()
def fast_hasher(monkeypatch):
    monkeypatch.setattr(auth, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


def test_audit_log_never_contains_passwords_or_hashes(session, admin_user, fast_hasher):
    user = auth.create_user(
        session, username="sara", password=PASSWORD, role=ROLE_RECEPTIONIST, acting_user=admin_user
    )
    auth.change_password(
        session, acting_user=user, current_password=PASSWORD, new_password=NEW_PASSWORD
    )
    auth.reset_user_password(
        session, user_id=user.id, new_password=RESET_PASSWORD, acting_user=admin_user
    )

    dump = json.dumps(
        [(r.old_values, r.new_values) for r in session.query(AuditLog).all()], default=str
    )
    for secret in (PASSWORD, NEW_PASSWORD, RESET_PASSWORD, "$argon2", user.password_hash):
        assert secret not in dump


def test_user_repr_does_not_expose_the_hash(session, admin_user, fast_hasher):
    user = auth.create_user(
        session, username="sara", password=PASSWORD, role=ROLE_RECEPTIONIST, acting_user=admin_user
    )
    assert user.password_hash not in repr(user)
    assert "argon2" not in repr(user)


def test_error_messages_never_echo_the_password(session, admin_user, fast_hasher):
    secret = "Zq9!x"  # too short on purpose
    with pytest.raises(ValidationError) as short:
        validate_password(secret)
    assert secret not in str(short.value)

    auth.create_user(
        session, username="sara", password=PASSWORD, role=ROLE_RECEPTIONIST, acting_user=admin_user
    )
    wrong = "Totally-Wrong-Guess-9"
    with pytest.raises(auth.AuthenticationError) as bad:
        auth.authenticate(
            session, username="sara", password=wrong, now=datetime(2026, 9, 3, tzinfo=timezone.utc)
        )
    assert wrong not in str(bad.value)


# --- secrets stay out of git -------------------------------------------------------


def test_gitignore_excludes_secrets():
    lines = {l.strip() for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert ".env" in lines
    assert "*.key" in lines