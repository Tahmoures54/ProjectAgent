# Path: pms_app/utils/notify.py
"""
Business SMS notifications — daily reports & concerns.
Never raises to the caller; failures are logged only.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Set

from flask import current_app, url_for

from pms_app.utils.sms import send_sms


def _app_name() -> str:
    try:
        return current_app.config.get("APP_NAME") or "Project Agent"
    except Exception:
        return "Project Agent"


def _enabled(flag: str, default: bool = True) -> bool:
    try:
        v = current_app.config.get(flag)
        if v is None:
            import os
            v = os.getenv(flag)
        if v is None:
            return default
        return str(v).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return default


def _user_can_receive(user) -> bool:
    if not user or not getattr(user, "is_active", True):
        return False
    phone = (getattr(user, "phone", None) or "").strip()
    if not phone:
        return False
    # transactional: allow if verified OR config allows unverified
    if hasattr(user, "can_receive_sms"):
        try:
            return bool(user.can_receive_sms(transactional=True))
        except Exception:
            pass
    if getattr(user, "phone_verified", False):
        return True
    return _enabled("SMS_ALLOW_UNVERIFIED_TRANSACTIONAL", True)


def _notify_user(user, message: str, purpose: str) -> None:
    if not _user_can_receive(user):
        return
    phone = (user.phone or "").strip()
    try:
        send_sms(to=phone, message=message, purpose=purpose, user_id=int(user.id))
    except Exception as exc:
        try:
            current_app.logger.warning("notify failed purpose=%s user=%s err=%s", purpose, getattr(user, "id", None), exc)
        except Exception:
            pass


def _unique_users(users: Iterable) -> List:
    seen: Set[int] = set()
    out = []
    for u in users:
        if not u or not getattr(u, "id", None):
            continue
        if u.id in seen:
            continue
        seen.add(u.id)
        out.append(u)
    return out


def _project_managers(project) -> List:
    """مدیران فعال پروژه + مدیر ثبت‌شده روی پروژه."""
    from pms_app.models.project_membership import ProjectMembership
    from pms_app.models.user import User

    users = []
    if project and getattr(project, "manager_id", None):
        m = User.query.get(project.manager_id)
        if m:
            users.append(m)
    if project and project.id:
        memberships = (
            ProjectMembership.query.filter_by(project_id=project.id, status="active")
            .filter(ProjectMembership.role.in_(["admin", "manager"]))
            .all()
        )
        for mem in memberships:
            if mem.user:
                users.append(mem.user)
    return _unique_users(users)


def _company_admins(company_id: Optional[int]) -> List:
    if not company_id:
        return []
    from pms_app.models.user import User
    from pms_app.models.role import Role
    from pms_app.models.association import user_roles

    try:
        q = (
            User.query.filter_by(company_id=company_id, is_active=True)
            .join(user_roles)
            .join(Role)
            .filter(Role.name.in_(["company_admin", "admin"]))
        )
        return list(q.limit(20).all())
    except Exception:
        return []


# ─── Daily Report notifications ───────────────────────────────────────────

def notify_daily_report_submitted(report) -> None:
    """به مدیران پروژه: گزارش جدید برای تأیید."""
    if not _enabled("SMS_NOTIFY_DAILY_REPORT", True):
        return
    try:
        project = report.project
        submitter = report.submitted_by
        name = (submitter.full_name or submitter.email) if submitter else "پیمانکار"
        date_s = str(report.report_date or "")
        proj = project.project_name if project else "پروژه"
        try:
            link = url_for("daily_reports.detail", report_id=report.id, _external=True)
        except Exception:
            link = f"/daily-reports/{report.id}"
        msg = (
            f"{_app_name()}\n"
            f"گزارش روزانه جدید برای تأیید\n"
            f"پروژه: {proj}\n"
            f"تاریخ: {date_s}\n"
            f"از: {name}\n"
            f"{link}"
        )
        recipients = _project_managers(project) + _company_admins(getattr(report, "company_id", None))
        for u in _unique_users(recipients):
            if submitter and u.id == submitter.id:
                continue
            _notify_user(u, msg, "DAILY_REPORT_SUBMITTED")
    except Exception as exc:
        try:
            current_app.logger.exception("notify_daily_report_submitted: %s", exc)
        except Exception:
            pass


def notify_daily_report_decision(report, *, decision: str) -> None:
    """به ارسال‌کننده: نتیجه بررسی (approve / reject / revision)."""
    if not _enabled("SMS_NOTIFY_DAILY_REPORT", True):
        return
    try:
        submitter = report.submitted_by
        if not submitter:
            return
        labels = {
            "approve": "تأیید شد",
            "reject": "رد شد",
            "request_revision": "نیاز به اصلاح دارد",
        }
        label = labels.get(decision, decision)
        proj = report.project.project_name if report.project else "پروژه"
        date_s = str(report.report_date or "")
        try:
            link = url_for("daily_reports.detail", report_id=report.id, _external=True)
        except Exception:
            link = f"/daily-reports/{report.id}"
        extra = ""
        if report.review_comment:
            extra = f"\nتوضیح: {(report.review_comment or '')[:80]}"
        msg = (
            f"{_app_name()}\n"
            f"گزارش روزانه شما {label}\n"
            f"پروژه: {proj}\n"
            f"تاریخ: {date_s}{extra}\n"
            f"{link}"
        )
        _notify_user(submitter, msg, f"DAILY_REPORT_{decision.upper()}")
    except Exception as exc:
        try:
            current_app.logger.exception("notify_daily_report_decision: %s", exp if False else exc)
        except Exception:
            pass


# ─── Concern notifications ────────────────────────────────────────────────

def notify_concern_created(concern) -> None:
    """به مسئول + مدیران (در صورت اولویت بالا/بحرانی)."""
    if not _enabled("SMS_NOTIFY_CONCERN", True):
        return
    try:
        try:
            link = url_for("concerns.detail", concern_id=concern.id, _external=True)
        except Exception:
            link = f"/concerns/{concern.id}"
        title = (concern.title or "")[:60]
        priority = concern.priority_label if hasattr(concern, "priority_label") else concern.priority
        msg = (
            f"{_app_name()}\n"
            f"کانسرن جدید ({priority})\n"
            f"{title}\n"
            f"{link}"
        )
        recipients = []
        if concern.assignee:
            recipients.append(concern.assignee)
        if concern.priority in ("high", "critical"):
            recipients.extend(_project_managers(concern.project))
            recipients.extend(_company_admins(concern.company_id))
        raised = concern.raised_by
        for u in _unique_users(recipients):
            if raised and u.id == raised.id:
                continue
            _notify_user(u, msg, "CONCERN_CREATED")
    except Exception as exc:
        try:
            current_app.logger.exception("notify_concern_created: %s", exc)
        except Exception:
            pass


def notify_concern_assigned(concern) -> None:
    if not _enabled("SMS_NOTIFY_CONCERN", True):
        return
    try:
        assignee = concern.assignee
        if not assignee:
            return
        try:
            link = url_for("concerns.detail", concern_id=concern.id, _external=True)
        except Exception:
            link = f"/concerns/{concern.id}"
        title = (concern.title or "")[:60]
        msg = (
            f"{_app_name()}\n"
            f"کانسرن به شما ارجاع شد\n"
            f"{title}\n"
            f"{link}"
        )
        _notify_user(assignee, msg, "CONCERN_ASSIGNED")
    except Exception as exc:
        try:
            current_app.logger.exception("notify_concern_assigned: %s", exc)
        except Exception:
            pass


def notify_concern_escalated(concern) -> None:
    if not _enabled("SMS_NOTIFY_CONCERN", True):
        return
    try:
        try:
            link = url_for("concerns.detail", concern_id=concern.id, _external=True)
        except Exception:
            link = f"/concerns/{concern.id}"
        title = (concern.title or "")[:60]
        msg = (
            f"{_app_name()}\n"
            f"⚠ کانسرن ارجاع‌شده (escalated)\n"
            f"{title}\n"
            f"{link}"
        )
        recipients = _project_managers(concern.project) + _company_admins(concern.company_id)
        if concern.assignee:
            recipients.append(concern.assignee)
        for u in _unique_users(recipients):
            _notify_user(u, msg, "CONCERN_ESCALATED")
    except Exception as exc:
        try:
            current_app.logger.exception("notify_concern_escalated: %s", exp if False else exc)
        except Exception:
            pass


def notify_concern_status(concern, *, action: str) -> None:
    """اطلاع به ثبت‌کننده هنگام resolve/close."""
    if not _enabled("SMS_NOTIFY_CONCERN", True):
        return
    if action not in ("resolve", "close", "reopen"):
        return
    try:
        raised = concern.raised_by
        if not raised:
            return
        labels = {"resolve": "حل شد", "close": "بسته شد", "reopen": "دوباره باز شد"}
        try:
            link = url_for("concerns.detail", concern_id=concern.id, _external=True)
        except Exception:
            link = f"/concerns/{concern.id}"
        title = (concern.title or "")[:60]
        msg = (
            f"{_app_name()}\n"
            f"کانسرن شما {labels.get(action, action)}\n"
            f"{title}\n"
            f"{link}"
        )
        _notify_user(raised, msg, f"CONCERN_{action.upper()}")
    except Exception as exc:
        try:
            current_app.logger.exception("notify_concern_status: %s", exp if False else exc)
        except Exception:
            pass
