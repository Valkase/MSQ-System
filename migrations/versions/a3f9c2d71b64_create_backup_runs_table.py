"""create backup_runs table

Revision ID: a3f9c2d71b64
Revises: 8bd5cca79952
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9c2d71b64'
down_revision: Union[str, Sequence[str], None] = '8bd5cca79952'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('backup_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('drive_id', sa.String(length=64), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('ok', 'failed', 'drive_missing')", name='ck_backup_runs_status_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_backup_runs_started_at'), 'backup_runs', ['started_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_backup_runs_started_at'), table_name='backup_runs')
    op.drop_table('backup_runs')