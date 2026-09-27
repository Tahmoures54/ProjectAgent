# Path: pms_app/models/action_item.py
"""
Action Plan items – practical task tracking linked to projects (and optionally contract items).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pms_app.extensions import db


def utcnow() -> datetime:
    return datetime.utcnow()


class ActionItem(db.Model):
    """
    Single action / task in a project's Action Plan.
    """
    __tablename__ = "action_items"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional link to a schedule / WBS activity
    contract_item_id = db.Column(
        db.Integer,
        db.ForeignKey("contract_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # open | in_progress | done | cancelled | blocked
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    # low | medium | high | critical
    priority = db.Column(db.String(20), nullable=False, default="medium", index=True)

    assignee_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    due_date = db.Column(db.Date, nullable=True, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Simple progress 0-100 for longer actions
    progress_percent = db.Column(db.Numeric(5, 2), nullable=True, default=0)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # Relationships
    company = db.relationship("Company", lazy="joined")
    project = db.relationship(
        "Project",
        backref=db.backref("action_items", lazy="dynamic", cascade="all, delete-orphan"),
        lazy="joined",
    )
    contract_item = db.relationship("ContractItem", lazy="joined")
    assignee = db.relationship("User", foreign_keys=[assignee_id], lazy="joined")
    created_by = db.relationship("User", foreign_keys=[created_by_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_action_items_project_status", "project_id", "status"),
        db.Index("ix_action_items_assignee_status", "assignee_id", "status"),
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    STATUS_LABELS = {
        "open": "باز",
        "in_progress": "در حال انجام",
        "done": "انجام‌شده",
        "cancelled": "لغو شده",
        "blocked": "مسدود",
    }

    PRIORITY_LABELS = {
        "low": "کم",
        "medium": "متوسط",
        "high": "بالا",
        "critical": "بحرانی",
    }

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def priority_label(self) -> str:
        return self.PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def is_overdue(self) -> bool:
        if self.status in ("done", "cancelled"):
            return False
        if not self.due_date:
            return False
        return self.due_date < date.today()

    @property
    def is_done(self) -> bool:
        return self.status == "done"

    history = db.relationship(
        "ActionItemHistory",
        back_populates="action",
        cascade="all, delete-orphan",
        order_by="ActionItemHistory.created_at.asc()",
        lazy="dynamic",
    )

    def add_history(
        self,
        *,
        user_id: Optional[int],
        action: str,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        note: Optional[str] = None,
    ) -> "ActionItemHistory":
        entry = ActionItemHistory(
            action_item=self,
            user_id=user_id,
            action=action,
            from_status=from_status,
            to_status=to_status or self.status,
            note=note,
        )
        db.session.add(entry)
        return entry

    def mark_done(self, user_id: Optional[int] = None, note: Optional[str] = None) -> None:
        old = self.status
        self.status = "done"
        self.progress_percent = 100
        self.completed_at = utcnow()
        self.add_history(
            user_id=user_id,
            action="status_change",
            from_status=old,
            to_status="done",
            note=note,
        )

    def __repr__(self) -> str:
        return f"<ActionItem id={self.id} project_id={self.project_id} title={self.title!r} status={self.status}>"


class ActionItemHistory(db.Model):
    """Immutable status/action trail for an ActionItem."""
    __tablename__ = "action_item_history"

    id = db.Column(db.Integer, primary_key=True)
    action_item_id = db.Column(
        db.Integer,
        db.ForeignKey("action_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = db.Column(db.String(50), nullable=False)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    action_item = db.relationship("ActionItem", back_populates="history")
    user = db.relationship("User", lazy="joined")

    __table_args__ = (
        db.Index("ix_action_item_history_action_created", "action", "created_at"),
        db.Index("ix_action_item_history_item_created", "action_item_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ActionItemHistory id={self.id} action_item_id={self.action_item_id} action={self.action!r}>"
