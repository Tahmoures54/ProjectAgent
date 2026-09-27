"""Add immutable audit history for action items."""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "action_item_history" in inspector.get_table_names():
        return
    op.create_table(
        "action_item_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_item_id", sa.Integer(), sa.ForeignKey("action_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_action_item_history_action_item_id", "action_item_history", ["action_item_id"])
    op.create_index("ix_action_item_history_user_id", "action_item_history", ["user_id"])
    op.create_index("ix_action_item_history_created_at", "action_item_history", ["created_at"])
    op.create_index("ix_action_item_history_action_created", "action_item_history", ["action", "created_at"])
    op.create_index("ix_action_item_history_item_created", "action_item_history", ["action_item_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "action_item_history" not in inspector.get_table_names():
        return
    op.drop_index("ix_action_item_history_item_created", table_name="action_item_history")
    op.drop_index("ix_action_item_history_action_created", table_name="action_item_history")
    op.drop_index("ix_action_item_history_created_at", table_name="action_item_history")
    op.drop_index("ix_action_item_history_user_id", table_name="action_item_history")
    op.drop_index("ix_action_item_history_action_item_id", table_name="action_item_history")
    op.drop_table("action_item_history")
