"""
One-time setup script: creates the first admin account.

Run this manually after the database and migrations are in place —
there is deliberately no in-app "create first admin" flow, since no
logged-in admin exists yet to authorize one.

Usage:
    python scripts/create_first_admin.py
"""

import getpass
import sys

from argon2 import PasswordHasher
from argon2.exceptions import HashingError
from sqlalchemy.exc import IntegrityError

from data.database import SessionLocal
from data.models.user import ROLE_ADMIN, User

ph = PasswordHasher()


def prompt_username(session) -> str:
    while True:
        username = input("Admin username: ").strip()
        if not username:
            print("Username can't be empty.")
            continue
        exists = session.query(User).filter(User.username == username).first()
        if exists:
            print(f"A user named '{username}' already exists. Choose another.")
            continue
        return username


def prompt_password() -> str:
    while True:
        password = getpass.getpass("Admin password: ")
        if len(password) < 8:
            print("Password must be at least 8 characters.")
            continue
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords didn't match. Try again.")
            continue
        return password


def create_first_admin() -> None:
    session = SessionLocal()
    try:
        existing_admin = (
            session.query(User).filter(User.role == ROLE_ADMIN).first()
        )
        if existing_admin:
            print(
                f"An admin account already exists ('{existing_admin.username}'). "
                "This script is only meant to create the first one. Aborting."
            )
            sys.exit(1)

        print("=== Create first admin account ===")
        username = prompt_username(session)
        password = prompt_password()

        try:
            password_hash = ph.hash(password)
        except HashingError as exc:
            print(f"Failed to hash password: {exc}")
            sys.exit(1)

        admin = User(
            username=username,
            password_hash=password_hash,
            role=ROLE_ADMIN,
            active=True,
        )
        session.add(admin)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            print("Could not create user — username may already be taken.")
            sys.exit(1)

        print(f"Admin account '{username}' created successfully.")

    finally:
        session.close()


if __name__ == "__main__":
    create_first_admin()