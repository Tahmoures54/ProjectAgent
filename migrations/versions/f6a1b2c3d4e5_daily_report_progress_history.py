"""daily report progress history

Revision ID: f6a1b2c3d4e5
Revises: e4c9d7a2b1f0
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e4c9d7a2b1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "daily_report_progress" in existing:
        return

    op.create_table(
        "daily_report_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contract_item_id",
            sa.Integer(),
            sa.ForeignKey("contract_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("location", sa.String(length=160), nullable=False),
        sa.Column("structure_tag", sa.String(length=120), nullable=True),
        sa.Column("progress_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("quantity_done", sa.Numeric(18, 4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "applied_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index(
        "ix_daily_report_progress_company_id",
        "daily_report_progress",
        ["company_id"],
    )
    op.create_index(
        "ix_daily_report_progress_project_id",
        "daily_report_progress",
        ["project_id"],
    )
    op.create_index(
        "ix_daily_report_progress_contract_item_id",
        "daily_report_progress",
        ["contract_item_id"],
    )
    op.create_index(
        "ix_daily_report_progress_structure_tag",
        "daily_report_progress",
        ["structure_tag"],
    )
    op.create_index(
        "ix_daily_report_progress_created_at",
        "daily_report_progress",
        ["created_at"],
    )
    op.create_index(
        "ix_daily_report_progress_project_item",
        "daily_report_progress",
        ["project_id", "contract_item_id"],
    )
    op.create_index(
        "ix_daily_report_progress_project_location",
        "daily_report_progress",
        ["project_id", "location"],
    )
    op.create_index(
        "ix_daily_report_progress_project_tag",
        "daily_report_progress",
        ["project_id", "structure_tag"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "daily_report_progress" not in set(inspector.get_table_names()):
        return
    op.drop_table("daily_report_progress")
