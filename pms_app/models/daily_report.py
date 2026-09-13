# Path: pms_app/models/daily_report.py
"""
Daily Site / Progress Report – modern multi-level approval workflow.

Best practices 2025/2026:
- Clear status machine (draft → submitted → under_review → approved | rejected | needs_revision)
- Structured fields for construction & project controls (manpower, equipment, work done, HSE, weather)
- Linked progress updates to ContractItems (applied only after final approval)
- Full audit trail of status transitions + comments
- Multi-tenant + project-scoped access
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pms_app.extensions import db


def utcnow() -> datetime:
    return datetime.utcnow()


class DailyReport(db.Model):
    """
    گزارش روزانه پیمانکار / گروه اجرایی.
    پس از تأیید نهایی مدیران، می‌تواند پیشرفت آیتم‌های قراردادی را به‌روز کند.
    """
    __tablename__ = "daily_reports"

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

    # تاریخ گزارش (میلادی در DB – نمایش جلالی در UI)
    report_date = db.Column(db.Date, nullable=False, index=True)

    # وضعیت گردش کار
    # draft | submitted | under_review | approved | rejected | needs_revision
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)

    # ارسال‌کننده (معمولاً پیمانکار / عضو اجرایی)
    submitted_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_at = db.Column(db.DateTime, nullable=True)

    # آخرین تأییدکننده / ردکننده
    reviewed_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_comment = db.Column(db.Text, nullable=True)

    # ——— محتوای گزارش (استاندارد کنترل پروژه) ———
    weather = db.Column(db.String(100), nullable=True)  # آفتابی، ابری، بارانی، ...
    temperature_min = db.Column(db.Numeric(5, 1), nullable=True)
    temperature_max = db.Column(db.Numeric(5, 1), nullable=True)

    # نیروی انسانی
    manpower_total = db.Column(db.Integer, nullable=True, default=0)
    manpower_details = db.Column(db.JSON, nullable=True)  # [{role, count}, ...]

    # ماشین‌آلات و تجهیزات
    equipment_details = db.Column(db.JSON, nullable=True)  # [{name, count, hours}, ...]

    # شرح کار انجام‌شده (متن آزاد)
    work_performed = db.Column(db.Text, nullable=True)

    # به‌روزرسانی پیشرفت آیتم‌ها (قبل از تأیید فقط پیشنهادی است)
    # [{contract_item_id, progress_percent, quantity_done, notes}, ...]
    progress_updates = db.Column(db.JSON, nullable=True)

    # مشکلات، تأخیرات، موانع
    issues_delays = db.Column(db.Text, nullable=True)

    # ایمنی، بهداشت و محیط زیست (HSE)
    hse_incidents = db.Column(db.Text, nullable=True)
    hse_observations = db.Column(db.Text, nullable=True)
    near_miss_count = db.Column(db.Integer, nullable=True, default=0)

    # بازدیدکنندگان / جلسات
    visitors_meetings = db.Column(db.Text, nullable=True)

    # یادداشت کلی
    notes = db.Column(db.Text, nullable=True)

    # ——— فیلدهای کنترل پروژه EPC ———
    # engineering | procurement | construction | mixed
    epc_phase = db.Column(db.String(40), nullable=True, index=True)
    work_area = db.Column(db.String(120), nullable=True)
    shift = db.Column(db.String(30), nullable=True)  # day | night | full
    lost_time_hours = db.Column(db.Numeric(8, 2), nullable=True)
    # [{name, qty, unit, vendor}]
    materials_received = db.Column(db.JSON, nullable=True)
    # [{doc_no, title, status}]
    engineering_outputs = db.Column(db.JSON, nullable=True)

    # آیا پیشرفت روی آیتم‌ها اعمال شده؟ (فقط بعد از approved)
    progress_applied = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # Relationships
    company = db.relationship("Company", lazy="joined")
    project = db.relationship(
        "Project",
        backref=db.backref("daily_reports", lazy="dynamic", cascade="all, delete-orphan"),
        lazy="joined",
    )
    submitted_by = db.relationship("User", foreign_keys=[submitted_by_id], lazy="joined")
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id], lazy="joined")

    history = db.relationship(
        "DailyReportHistory",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="DailyReportHistory.created_at.asc()",
        lazy="dynamic",
    )

    __table_args__ = (
        db.Index("ix_daily_reports_project_date", "project_id", "report_date"),
        db.Index("ix_daily_reports_project_status", "project_id", "status"),
        db.Index("ix_daily_reports_company_status", "company_id", "status"),
        db.UniqueConstraint(
            "project_id", "report_date", "submitted_by_id",
            name="uq_daily_report_project_date_user",
        ),
    )

    # ------------------------------------------------------------------
    # Labels & helpers
    # ------------------------------------------------------------------
    STATUS_LABELS = {
        "draft": "پیش‌نویس",
        "submitted": "ارسال‌شده",
        "under_review": "در حال بررسی",
        "approved": "تأیید شده",
        "rejected": "رد شده",
        "needs_revision": "نیاز به اصلاح",
    }

    STATUS_COLORS = {
        "draft": "slate",
        "submitted": "blue",
        "under_review": "amber",
        "approved": "emerald",
        "rejected": "rose",
        "needs_revision": "orange",
    }

    WEATHER_LABELS = {
        "sunny": "آفتابی",
        "partly_cloudy": "نیمه‌ابری",
        "cloudy": "ابری",
        "rainy": "بارانی",
        "stormy": "طوفانی",
        "snowy": "برفی",
        "foggy": "مه",
        "windy": "باد شدید",
        "other": "سایر",
    }

    SHIFT_LABELS = {
        "day": "روزکار",
        "night": "شب‌کار",
        "full": "تمام‌وقت / دو شیفت",
    }

    EPC_PHASE_LABELS = {
        "engineering": "مهندسی (E)",
        "procurement": "تدارکات (P)",
        "construction": "اجرا (C)",
        "mixed": "ترکیبی EPC",
    }

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self) -> str:
        return self.STATUS_COLORS.get(self.status, "slate")

    @property
    def weather_label(self) -> str:
        if not self.weather:
            return "—"
        return self.WEATHER_LABELS.get(self.weather, self.weather)

    @property
    def shift_label(self) -> str:
        if not self.shift:
            return "—"
        return self.SHIFT_LABELS.get(self.shift, self.shift)

    @property
    def epc_phase_label(self) -> str:
        if not self.epc_phase:
            return "—"
        return self.EPC_PHASE_LABELS.get(self.epc_phase, self.epc_phase)

    @property
    def is_editable(self) -> bool:
        return self.status in ("draft", "needs_revision")

    @property
    def is_pending_approval(self) -> bool:
        return self.status in ("submitted", "under_review")

    @property
    def is_final(self) -> bool:
        return self.status in ("approved", "rejected")

    def add_history(
        self,
        *,
        user_id: Optional[int],
        action: str,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> "DailyReportHistory":
        entry = DailyReportHistory(
            report=self,
            user_id=user_id,
            action=action,
            from_status=from_status,
            to_status=to_status or self.status,
            comment=comment,
        )
        db.session.add(entry)
        return entry

    def submit(self, user_id: int) -> None:
        if self.status not in ("draft", "needs_revision"):
            raise ValueError("فقط پیش‌نویس یا گزارش نیازمند اصلاح قابل ارسال است.")
        old = self.status
        self.status = "submitted"
        self.submitted_by_id = user_id
        self.submitted_at = utcnow()
        self.reviewed_by_id = None
        self.reviewed_at = None
        self.review_comment = None
        self.add_history(
            user_id=user_id,
            action="submit",
            from_status=old,
            to_status="submitted",
            comment="گزارش برای تأیید ارسال شد.",
        )

    def start_review(self, user_id: int) -> None:
        if self.status != "submitted":
            raise ValueError("فقط گزارش ارسال‌شده قابل بررسی است.")
        old = self.status
        self.status = "under_review"
        self.reviewed_by_id = user_id
        self.add_history(
            user_id=user_id,
            action="start_review",
            from_status=old,
            to_status="under_review",
        )

    def approve(self, user_id: int, comment: Optional[str] = None, apply_progress: bool = True) -> None:
        if self.status not in ("submitted", "under_review"):
            raise ValueError("وضعیت فعلی اجازه تأیید ندارد.")
        old = self.status
        self.status = "approved"
        self.reviewed_by_id = user_id
        self.reviewed_at = utcnow()
        self.review_comment = comment
        self.add_history(
            user_id=user_id,
            action="approve",
            from_status=old,
            to_status="approved",
            comment=comment or "تأیید نهایی",
        )
        if apply_progress and not self.progress_applied:
            self._apply_progress_updates()

    def reject(self, user_id: int, comment: str) -> None:
        if self.status not in ("submitted", "under_review"):
            raise ValueError("وضعیت فعلی اجازه رد ندارد.")
        if not (comment or "").strip():
            raise ValueError("دلیل رد الزامی است.")
        old = self.status
        self.status = "rejected"
        self.reviewed_by_id = user_id
        self.reviewed_at = utcnow()
        self.review_comment = comment
        self.add_history(
            user_id=user_id,
            action="reject",
            from_status=old,
            to_status="rejected",
            comment=comment,
        )

    def request_revision(self, user_id: int, comment: str) -> None:
        if self.status not in ("submitted", "under_review"):
            raise ValueError("وضعیت فعلی اجازه درخواست اصلاح ندارد.")
        if not (comment or "").strip():
            raise ValueError("توضیح اصلاح الزامی است.")
        old = self.status
        self.status = "needs_revision"
        self.reviewed_by_id = user_id
        self.reviewed_at = utcnow()
        self.review_comment = comment
        self.add_history(
            user_id=user_id,
            action="request_revision",
            from_status=old,
            to_status="needs_revision",
            comment=comment,
        )

    def _apply_progress_updates(self) -> None:
        """اعمال درصد پیشرفت روی ContractItemها پس از تأیید نهایی."""
        if not self.progress_updates or self.progress_applied:
            return
        from pms_app.models.item import ContractItem

        for upd in self.progress_updates:
            item_id = upd.get("contract_item_id")
            if not item_id:
                continue
            item = db.session.get(ContractItem, int(item_id))
            if not item:
                continue
            if int(item.company_id or 0) != int(self.company_id or 0):
                continue
            if not item.contract or item.contract.project_id != self.project_id:
                continue
            pct = upd.get("progress_percent")
            if pct is not None:
                try:
                    item.actual_progress_percentage = Decimal(str(pct))
                except Exception:
                    pass
            qty = upd.get("quantity_done")
            if qty is not None and hasattr(item, "actual_quantity"):
                try:
                    item.actual_quantity = Decimal(str(qty))
                except Exception:
                    pass
        self.progress_applied = True

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "status": self.status,
            "status_label": self.status_label,
            "manpower_total": self.manpower_total,
            "submitted_by": self.submitted_by.full_name or self.submitted_by.email if self.submitted_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<DailyReport id={self.id} project_id={self.project_id} "
            f"date={self.report_date} status={self.status}>"
        )


class DailyReportHistory(db.Model):
    """تاریخچه تغییرات وضعیت گزارش روزانه (audit trail)."""
    __tablename__ = "daily_report_history"

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(
        db.Integer,
        db.ForeignKey("daily_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action = db.Column(db.String(50), nullable=False)  # create, submit, approve, reject, ...
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=True)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    report = db.relationship("DailyReport", back_populates="history")
    user = db.relationship("User", lazy="joined")

    def __repr__(self) -> str:
        return f"<DailyReportHistory id={self.id} report_id={self.report_id} action={self.action}>"
