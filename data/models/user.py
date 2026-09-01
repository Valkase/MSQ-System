"""
User model — receptionist/admin accounts.

Notes:
- `password_hash` stores an argon2/bcrypt hash, never a plaintext password.
- `role` is a simple string constrained to the two confirmed roles.
- `active` supports soft-disabling an account (Phase 3: admin can deactivate,
  never hard-delete a user).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from data.database import Base

ROLE_ADMIN = "admin"
ROLE_RECEPTIONIST = "receptionist"
VALID_ROLES = (ROLE_ADMIN, ROLE_RECEPTIONIST)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {VALID_ROLES}", name="ck_users_role_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<User username={self.username!r} role={self.role!r} active={self.active}>"