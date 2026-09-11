"""daily reports + concerns tables

Revision ID: a1b2c3d4e5f6
Revises: eb596cd712d0
Create Date: 2026-09-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "eb596cd712d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "daily_reports" not in existing:
        op.create_table(
            "daily_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
            sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("review_comment", sa.Text(), nullable=True),
            sa.Column("weather", sa.String(100), nullable=True),
            sa.Column("temperature_min", sa.Numeric(5, 1), nullable=True),
            sa.Column("temperature_max", sa.Numeric(5, 1), nullable=True),
            sa.Column("manpower_total", sa.Integer(), nullable=True),
            sa.Column("manpower_details", sa.JSON(), nullable=True),
            sa.Column("equipment_details", sa.JSON(), nullable=True),
            sa.Column("work_performed", sa.Text(), nullable=True),
            sa.Column("progress_updates", sa.JSON(), nullable=True),
            sa.Column("issues_delays", sa.Text(), nullable=True),
            sa.Column("hse_incidents", sa.Text(), nullable=True),
            sa.Column("hse_observations", sa.Text(), nullable=True),
            sa.Column("near_miss_count", sa.Integer(), nullable=True),
            sa.Column("visitors_meetings", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("progress_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "project_id",
                "report_date",
                "submitted_by_id",
                name="uq_daily_report_project_date_user",
            ),
        )
        op.create_index("ix_daily_reports_company_id", "daily_reports", ["company_id"])
        op.create_index("ix_daily_reports_project_id", "daily_reports", ["project_id"])
        op.create_index("ix_daily_reports_report_date", "daily_reports", ["report_date"])
        op.create_index("ix_daily_reports_status", "daily_reports", ["status"])
        op.create_index("ix_daily_reports_project_date", "daily_reports", ["project_id", "report_date"])
        op.create_index("ix_daily_reports_project_status", "daily_reports", ["project_id", "status"])
        op.create_index("ix_daily_reports_company_status", "daily_reports", ["company_id", "status"])

    if "daily_report_history" not in existing:
        op.create_table(
            "daily_report_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "report_id",
                sa.Integer(),
                sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("from_status", sa.String(30), nullable=True),
            sa.Column("to_status", sa.String(30), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_daily_report_history_report_id", "daily_report_history", ["report_id"])

    if "concerns" not in existing:
        op.create_table(
            "concerns",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("title", sa.String(250), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(40), nullable=False, server_default="other"),
            sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(30), nullable=False, server_default="open"),
            sa.Column("visibility", sa.String(30), nullable=False, server_default="project"),
            sa.Column("raised_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("assignee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("resolution", sa.Text(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("related_action_item_id", sa.Integer(), nullable=True),
            sa.Column("related_daily_report_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_concerns_company_id", "concerns", ["company_id"])
        op.create_index("ix_concerns_project_id", "concerns", ["project_id"])
        op.create_index("ix_concerns_title", "concerns", ["title"])
        op.create_index("ix_concerns_status", "concerns", ["status"])
        op.create_index("ix_concerns_priority", "concerns", ["priority"])
        op.create_index("ix_concerns_company_status", "concerns", ["company_id", "status"])
        op.create_index("ix_concerns_project_status", "concerns", ["project_id", "status"])
        op.create_index("ix_concerns_visibility", "concerns", ["visibility"])
        op.create_index("ix_concerns_assignee_status", "concerns", ["assignee_id", "status"])

    if "concern_comments" not in existing:
        op.create_table(
            "concern_comments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("concern_id", sa.Integer(), sa.ForeignKey("concerns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_concern_comments_concern_id", "concern_comments", ["concern_id"])

    if "concern_history" not in existing:
        op.create_table(
            "concern_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("concern_id", sa.Integer(), sa.ForeignKey("concerns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(50), nullable=False),
            sa.Column("from_status", sa.String(30), nullable=True),
            sa.Column("to_status", sa.String(30), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_concern_history_concern_id", "concern_history", ["concern_id"])


def downgrade() -> None:
    op.drop_table("concern_history")
    op.drop_table("concern_comments")
    op.drop_table("concerns")
    op.drop_table("daily_report_history")
    op.drop_table("daily_reports")
