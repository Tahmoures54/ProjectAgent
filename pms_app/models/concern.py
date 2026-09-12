# Path: pms_app/models/concern.py
"""
Concerns / Working Concerns – modern issue & concern management.

Best practices 2025/2026:
- Explicit visibility levels (who can see)
- Scope: company-wide or project-linked
- Status workflow + priority + category
- Assignment, escalation, comments, audit trail
- Multi-tenant isolation
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pms_app.extensions import db


def utcnow() -> datetime:
    return datetime.utcnow()


class Concern(db.Model):
    """
    کانسرن / دغدغه کاری.

    visibility:
      - private       → فقط ثبت‌کننده + مسئول + ادمین شرکت / مالک
      - project       → همه اعضای فعال پروژه (+ ادمین شرکت)
      - company       → همه کاربران شرکت
      - managers_only → مدیران پروژه، ادمین شرکت، مالک
    """
    __tablename__ = "concerns"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # اختیاری: کانسرن سطح پروژه
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    title = db.Column(db.String(250), nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    # technical | schedule | cost | safety | quality | resource | contractual | organizational | other
    category = db.Column(db.String(40), nullable=False, default="other", index=True)

    # low | medium | high | critical
    priority = db.Column(db.String(20), nullable=False, default="medium", index=True)

    # open | acknowledged | in_progress | resolved | closed | escalated
    status = db.Column(db.String(30), nullable=False, default="open", index=True)

    # private | project | company | managers_only
    visibility = db.Column(db.String(30), nullable=False, default="project", index=True)

    # ثبت‌کننده
    raised_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # مسئول رسیدگی
    assignee_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    due_date = db.Column(db.Date, nullable=True, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # راه‌حل / نتیجه
    resolution = db.Column(db.Text, nullable=True)

    # تگ‌ها (JSON list of strings)
    tags = db.Column(db.JSON, nullable=True)

    # اختیاری: لینک به action item یا daily report
    related_action_item_id = db.Column(db.Integer, nullable=True)
    related_daily_report_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # Relationships
    company = db.relationship("Company", lazy="joined")
    project = db.relationship(
        "Project",
        backref=db.backref("concerns", lazy="dynamic", cascade="all, delete-orphan"),
        lazy="joined",
    )
    raised_by = db.relationship("User", foreign_keys=[raised_by_id], lazy="joined")
    assignee = db.relationship("User", foreign_keys=[assignee_id], lazy="joined")

    comments = db.relationship(
        "ConcernComment",
        back_populates="concern",
        cascade="all, delete-orphan",
        order_by="ConcernComment.created_at.asc()",
        lazy="dynamic",
    )
    history = db.relationship(
        "ConcernHistory",
        back_populates="concern",
        cascade="all, delete-orphan",
        order_by="ConcernHistory.created_at.asc()",
        lazy="dynamic",
    )

    __table_args__ = (
        db.Index("ix_concerns_company_status", "company_id", "status"),
        db.Index("ix_concerns_project_status", "project_id", "status"),
        db.Index("ix_concerns_assignee_status", "assignee_id", "status"),
    )

    # ------------------------------------------------------------------
    CATEGORY_LABELS = {
        "technical": "فنی / اجرایی",
        "schedule": "زمان‌بندی",
        "cost": "هزینه / مالی",
        "safety": "ایمنی (HSE)",
        "quality": "کیفیت",
        "resource": "منابع انسانی / تجهیزات",
        "contractual": "قراردادی",
        "organizational": "سازمانی / فرآیندی",
        "other": "سایر",
    }

    PRIORITY_LABELS = {
        "low": "کم",
        "medium": "متوسط",
        "high": "بالا",
        "critical": "بحرانی",
    }

    STATUS_LABELS = {
        "open": "باز",
        "acknowledged": "دریافت‌شده",
        "in_progress": "در حال رسیدگی",
        "resolved": "حل‌شده",
        "closed": "بسته",
        "escalated": "ارجاع‌شده (بالاتر)",
    }

    VISIBILITY_LABELS = {
        "private": "خصوصی (ثبت‌کننده + مسئول + ادمین)",
        "project": "اعضای پروژه",
        "company": "کل شرکت",
        "managers_only": "فقط مدیران",
    }

    @property
    def category_label(self) -> str:
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def priority_label(self) -> str:
        return self.PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def visibility_label(self) -> str:
        return self.VISIBILITY_LABELS.get(self.visibility, self.visibility)

    @property
    def is_open(self) -> bool:
        return self.status in ("open", "acknowledged", "in_progress", "escalated")

    @property
    def is_closed_like(self) -> bool:
        return self.status in ("resolved", "closed")

    def add_history(
        self,
        *,
        user_id: Optional[int],
        action: str,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        note: Optional[str] = None,
    ) -> "ConcernHistory":
        entry = ConcernHistory(
            concern=self,
            user_id=user_id,
            action=action,
            from_status=from_status,
            to_status=to_status or self.status,
            note=note,
        )
        db.session.add(entry)
        return entry

    def acknowledge(self, user_id: int) -> None:
        if self.status != "open":
            raise ValueError("فقط کانسرن باز قابل دریافت است.")
        old = self.status
        self.status = "acknowledged"
        self.add_history(user_id=user_id, action="acknowledge", from_status=old, to_status="acknowledged")

    def start_progress(self, user_id: int) -> None:
        if self.status not in ("open", "acknowledged", "escalated"):
            raise ValueError("وضعیت فعلی اجازه شروع رسیدگی ندارد.")
        old = self.status
        self.status = "in_progress"
        if not self.assignee_id:
            self.assignee_id = user_id
        self.add_history(user_id=user_id, action="start_progress", from_status=old, to_status="in_progress")

    def resolve(self, user_id: int, resolution: Optional[str] = None) -> None:
        if self.status in ("resolved", "closed"):
            raise ValueError("این کانسرن قبلاً بسته شده است.")
        old = self.status
        self.status = "resolved"
        self.resolved_at = utcnow()
        if resolution:
            self.resolution = resolution
        self.add_history(
            user_id=user_id,
            action="resolve",
            from_status=old,
            to_status="resolved",
            note=resolution,
        )

    def close(self, user_id: int, note: Optional[str] = None) -> None:
        old = self.status
        self.status = "closed"
        self.closed_at = utcnow()
        self.add_history(user_id=user_id, action="close", from_status=old, to_status="closed", note=note)

    def escalate(self, user_id: int, note: Optional[str] = None) -> None:
        if self.status in ("resolved", "closed"):
            raise ValueError("کانسرن بسته‌شده قابل ارجاع نیست.")
        old = self.status
        self.status = "escalated"
        self.priority = "critical" if self.priority != "critical" else self.priority
        self.add_history(
            user_id=user_id,
            action="escalate",
            from_status=old,
            to_status="escalated",
            note=note or "ارجاع به سطح بالاتر",
        )

    def reopen(self, user_id: int, note: Optional[str] = None) -> None:
        if self.status not in ("resolved", "closed"):
            raise ValueError("فقط کانسرن حل‌شده یا بسته قابل بازگشایی است.")
        old = self.status
        self.status = "open"
        self.resolved_at = None
        self.closed_at = None
        self.add_history(user_id=user_id, action="reopen", from_status=old, to_status="open", note=note)

    def can_view(self, user) -> bool:
        """بررسی دسترسی مشاهده بر اساس visibility و نقش."""
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_owner", False):
            return True

        # باید همان شرکت باشد
        if getattr(user, "company_id", None) != self.company_id:
            return False

        project = self.project
        if project is not None and getattr(project, "company_id", None) != self.company_id:
            return False

        if getattr(user, "is_company_admin", False):
            return True

        uid = user.id

        # ثبت‌کننده و مسئول همیشه می‌بینند
        if self.raised_by_id == uid or self.assignee_id == uid:
            return True

        vis = self.visibility or "project"

        if vis == "private":
            return False  # فقط raised_by / assignee / admin که بالاتر چک شد

        if vis == "company":
            return True

        if vis == "managers_only":
            from pms_app.utils.access import user_manages_project

            return user_manages_project(user, self.project_id)

        if vis == "project":
            if not self.project_id:
                # بدون پروژه → مثل company برای اعضای شرکت با دسترسی
                return user.has_permission("concerns.read") or user.has_role("company_user")
            from pms_app.models.project_membership import ProjectMembership

            m = ProjectMembership.query.filter_by(
                project_id=self.project_id, user_id=uid, status="active"
            ).first()
            return m is not None

        return False

    def can_edit(self, user) -> bool:
        if not self.can_view(user):
            return False
        if getattr(user, "is_owner", False) or getattr(user, "is_company_admin", False):
            return True
        if self.raised_by_id == user.id and self.status in ("open", "acknowledged"):
            return True
        if self.assignee_id == user.id:
            return True
        if user.has_permission("concerns.manage"):
            return True
        return False

    def __repr__(self) -> str:
        return f"<Concern id={self.id} title={self.title!r} status={self.status} vis={self.visibility}>"


class ConcernComment(db.Model):
    __tablename__ = "concern_comments"

    id = db.Column(db.Integer, primary_key=True)
    concern_id = db.Column(
        db.Integer,
        db.ForeignKey("concerns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=False)  # فقط مدیران
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    concern = db.relationship("Concern", back_populates="comments")
    user = db.relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<ConcernComment id={self.id} concern_id={self.concern_id}>"


class ConcernHistory(db.Model):
    __tablename__ = "concern_history"

    id = db.Column(db.Integer, primary_key=True)
    concern_id = db.Column(
        db.Integer,
        db.ForeignKey("concerns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action = db.Column(db.String(50), nullable=False)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    concern = db.relationship("Concern", back_populates="history")
    user = db.relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<ConcernHistory id={self.id} action={self.action}>"
