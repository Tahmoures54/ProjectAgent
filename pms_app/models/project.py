from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.associationproxy import association_proxy

from pms_app.extensions import db


def utcnow() -> datetime:
    return datetime.utcnow()


class Project(db.Model):
    """
    Project master – multi-tenant, with baseline dates and control fields
    for EVM / portfolio reporting.
    """
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)

    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identity
    project_code = db.Column(db.String(50), nullable=False, index=True)
    project_name = db.Column(db.String(200), nullable=False, index=True)
    industry = db.Column(db.String(50), nullable=False, index=True)
    client_name = db.Column(db.String(200), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    base_currency = db.Column(db.String(10), nullable=False)

    # Current plan dates
    start_date = db.Column(db.Date, nullable=True)
    finish_date = db.Column(db.Date, nullable=True)

    # Baseline (original approved plan) – for schedule variance at project level
    baseline_start_date = db.Column(db.Date, nullable=True)
    baseline_finish_date = db.Column(db.Date, nullable=True)

    # Optional project-level BAC override (if not aggregated only from items)
    total_budget = db.Column(db.Numeric(18, 2), nullable=True)

    # Reporting / control
    data_date = db.Column(db.Date, nullable=True)  # as-of date for EVM snapshots
    manager_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    company = db.relationship(
        "Company",
        backref=db.backref("projects", lazy="dynamic"),
        lazy="joined",
    )
    manager = db.relationship("User", foreign_keys=[manager_id], lazy="joined")

    members = association_proxy("memberships", "user")

    __table_args__ = (
        db.UniqueConstraint("company_id", "project_code", name="uq_projects_company_code"),
        db.Index("ix_projects_company_status", "company_id", "status"),
    )

    @property
    def active_member_count(self) -> int:
        from pms_app.models.project_membership import ProjectMembership
        return (
            db.session.query(ProjectMembership)
            .filter_by(project_id=self.id, status="active")
            .count()
        )

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def has_member(self, user) -> bool:
        from pms_app.models.project_membership import ProjectMembership
        if not user or not user.id:
            return False
        return (
            ProjectMembership.query.filter_by(
                project_id=self.id,
                user_id=user.id,
                status="active",
            ).first()
            is not None
        )

    def can_access(self, user) -> bool:
        if not user or not user.is_active:
            return False
        if user.is_owner:
            return True
        if self.company_id != user.company_id:
            return False
        if user.is_company_admin:
            return True
        return self.has_member(user)

    STATUS_TITLES = {
        "active": "فعال",
        "on_hold": "متوقف",
        "closed": "بسته",
        "completed": "تکمیل‌شده",
        "cancelled": "لغو شده",
        "delayed": "تأخیردار",
    }

    @property
    def status_title(self) -> str:
        return self.STATUS_TITLES.get(self.status, self.status or "نامشخص")

    @property
    def is_delayed(self) -> bool:
        if self.status != "active" or not self.finish_date:
            return False
        return self.finish_date < date.today()

    @property
    def progress(self) -> float:
        """Weighted physical progress (0–100) for dashboard / lists."""
        try:
            from pms_app.utils.progress import project_progress

            return float(project_progress(self).get("overall_pct") or 0)
        except Exception:
            pct = self.percent_complete
            try:
                return float(pct or 0)
            except (TypeError, ValueError):
                return 0.0

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id} company_id={self.company_id} "
            f"code={self.project_code!r} name={self.project_name!r}>"
        )

    def get_evm(self, as_of: Optional[date] = None):
        from pms_app.utils.evm import project_evm
        return project_evm(self, as_of=as_of or self.data_date)

    @property
    def bac(self) -> Optional[Decimal]:
        if self.total_budget is not None:
            return Decimal(str(self.total_budget))
        result = self.get_evm()
        return result.bac if result.bac > 0 else None

    @property
    def earned_value(self) -> Optional[Decimal]:
        return self.get_evm().ev

    @property
    def actual_cost_total(self) -> Optional[Decimal]:
        return self.get_evm().ac

    @property
    def cpi(self) -> Optional[Decimal]:
        return self.get_evm().cpi

    @property
    def spi(self) -> Optional[Decimal]:
        return self.get_evm().spi

    @property
    def percent_complete(self) -> Optional[Decimal]:
        return self.get_evm().percent_complete

    @property
    def eac(self) -> Optional[Decimal]:
        return self.get_evm().eac

    def evm_summary(self) -> dict:
        return self.get_evm().as_dict()
