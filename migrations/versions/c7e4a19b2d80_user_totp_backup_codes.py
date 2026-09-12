"""Add hashed TOTP backup codes on users.

Revision ID: c7e4a19b2d80
Revises: a1b2c3d4e5f6
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e4a19b2d80"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "two_fa_backup_hashes" not in columns:
        op.add_column("users", sa.Column("two_fa_backup_hashes", sa.Text(), nullable=True))
    if "two_fa_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column("two_fa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "two_fa_secret" not in columns:
        op.add_column("users", sa.Column("two_fa_secret", sa.String(length=255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "two_fa_backup_hashes" in columns:
        op.drop_column("users", "two_fa_backup_hashes")
