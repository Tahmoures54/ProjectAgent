"""Optimize Progress Traceability history lookups.

Revision ID: 20260927_progress_traceability
Revises:
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "20260927_progress_traceability"
down_revision = None
branch_labels = None
depends_on = None


INDEX_NAME = "ix_daily_report_progress_traceability_history"


def upgrade() -> None:
    """Speed up previous-progress lookups by project/item/location/tag/time."""
    op.create_index(
        INDEX_NAME,
        "daily_report_progress",
        [
            "project_id",
            "contract_item_id",
            "location",
            "structure_tag",
            "created_at",
            "id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="daily_report_progress")
