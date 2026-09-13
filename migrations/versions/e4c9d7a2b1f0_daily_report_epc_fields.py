"""EPC fields on daily reports

Revision ID: e4c9d7a2b1f0
Revises: c7e4a19b2d80
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4c9d7a2b1f0"
down_revision: Union[str, Sequence[str], None] = "c7e4a19b2d80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_reports" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("daily_reports")}
    if "epc_phase" not in columns:
        op.add_column("daily_reports", sa.Column("epc_phase", sa.String(length=40), nullable=True))
        op.create_index("ix_daily_reports_epc_phase", "daily_reports", ["epc_phase"])
    if "work_area" not in columns:
        op.add_column("daily_reports", sa.Column("work_area", sa.String(length=120), nullable=True))
    if "shift" not in columns:
        op.add_column("daily_reports", sa.Column("shift", sa.String(length=30), nullable=True))
    if "lost_time_hours" not in columns:
        op.add_column("daily_reports", sa.Column("lost_time_hours", sa.Numeric(8, 2), nullable=True))
    if "materials_received" not in columns:
        op.add_column("daily_reports", sa.Column("materials_received", sa.JSON(), nullable=True))
    if "engineering_outputs" not in columns:
        op.add_column("daily_reports", sa.Column("engineering_outputs", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_reports" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("daily_reports")}
    for name in (
        "engineering_outputs",
        "materials_received",
        "lost_time_hours",
        "shift",
        "work_area",
        "epc_phase",
    ):
        if name in columns:
            op.drop_column("daily_reports", name)
