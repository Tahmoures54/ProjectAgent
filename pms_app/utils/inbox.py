# Path: pms_app/utils/inbox.py
"""
Workspace helpers: scoped queries, dashboard KPIs, in-app inbox, global search.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from flask import url_for
from sqlalchemy import or_

from pms_app.extensions import db
from pms_app.models.concern import Concern
from pms_app.models.contract import Contract
from pms_app.models.daily_report import DailyReport
from pms_app.models.project import Project
from pms_app.models.project_membership import ProjectMembership


PENDING_REPORT_STATUSES = ("submitted", "under_review")
OPEN_CONCERN_STATUSES = ("open", "acknowledged", "in_progress", "escalated")


def accessible_projects_query(user):
    """Projects the user is allowed to see (owner / company admin / membership)."""
    query = Project.query
    if not user or not getattr(user, "is_authenticated", False):
        return query.filter(Project.id == -1)
    if getattr(user, "is_owner", False):
        return query
    cid = getattr(user, "company_id", None)
    if getattr(user, "is_company_admin", False) and cid:
        return query.filter(Project.company_id == cid)
    if cid is None:
        return query.filter(Project.id == -1)
    return (
        query.join(ProjectMembership)
        .filter(ProjectMembership.user_id == user.id)
        .filter(ProjectMembership.status == "active")
    )


def accessible_project_ids(user) -> List[int]:
    rows = accessible_projects_query(user).with_entities(Project.id).all()
    return [int(r[0]) for r in rows]


def visible_concerns_query(user):
    """Concerns the user may view, matching concerns blueprint visibility rules."""
    query = Concern.query
    if not user or not getattr(user, "is_authenticated", False):
        return query.filter(Concern.id == -1)
    if getattr(user, "is_owner", False):
        return query

    cid = getattr(user, "company_id", None)
    if cid is None:
        return query.filter(Concern.id == -1)
    query = query.filter(Concern.company_id == cid)
    if getattr(user, "is_company_admin", False):
        return query

    uid = user.id
    member_project_ids = [
        m.project_id
        for m in ProjectMembership.query.filter_by(user_id=uid, status="active").all()
    ]
    manager_project_ids = [
        m.project_id
        for m in ProjectMembership.query.filter_by(user_id=uid, status="active")
        .filter(ProjectMembership.role.in_(["admin", "manager"]))
        .all()
    ]
    conditions = [
        Concern.raised_by_id == uid,
        Concern.assignee_id == uid,
        Concern.visibility == "company",
    ]
    if member_project_ids:
        conditions.append(
            db.and_(Concern.visibility == "project", Concern.project_id.in_(member_project_ids))
        )
    if manager_project_ids or (hasattr(user, "has_role") and user.has_role("manager")):
        conditions.append(Concern.visibility == "managers_only")
        if manager_project_ids:
            conditions.append(
                db.and_(
                    Concern.visibility == "managers_only",
                    or_(Concern.project_id.in_(manager_project_ids), Concern.project_id.is_(None)),
                )
            )
    return query.filter(or_(*conditions))


def scoped_daily_reports_query(user):
    query = DailyReport.query
    if not user or not getattr(user, "is_authenticated", False):
        return query.filter(DailyReport.id == -1)
    if getattr(user, "is_owner", False):
        return query
    cid = getattr(user, "company_id", None)
    if cid is None:
        return query.filter(DailyReport.id == -1)
    query = query.filter(DailyReport.company_id == cid)
    if getattr(user, "is_company_admin", False):
        return query
    return (
        query.join(ProjectMembership, ProjectMembership.project_id == DailyReport.project_id)
        .filter(ProjectMembership.user_id == user.id)
        .filter(ProjectMembership.status == "active")
    )


def dashboard_kpis(user, *, project_ids: Optional[Sequence[int]] = None) -> Dict[str, int]:
    ids = list(project_ids if project_ids is not None else accessible_project_ids(user))
    today = date.today()

    empty = {
        "total_projects": 0,
        "total_contracts": 0,
        "ongoing_projects": 0,
        "delayed_projects": 0,
        "pending_reports": 0,
        "open_concerns": 0,
        "critical_concerns": 0,
    }
    if not ids:
        return empty

    total_projects = (
        db.session.query(db.func.count(db.distinct(Project.id)))
        .filter(Project.id.in_(ids))
        .scalar()
        or 0
    )

    total_contracts = (
        db.session.query(db.func.count(Contract.id))
        .filter(Contract.project_id.in_(ids), Contract.status == "active")
        .scalar()
        or 0
    )
    ongoing_projects = (
        db.session.query(db.func.count(Project.id))
        .filter(Project.id.in_(ids), Project.status == "active")
        .scalar()
        or 0
    )
    delayed_projects = (
        db.session.query(db.func.count(Project.id))
        .filter(
            Project.id.in_(ids),
            Project.status == "active",
            Project.finish_date.isnot(None),
            Project.finish_date < today,
        )
        .scalar()
        or 0
    )
    pending_reports = (
        scoped_daily_reports_query(user)
        .filter(DailyReport.status.in_(PENDING_REPORT_STATUSES))
        .count()
    )
    open_q = visible_concerns_query(user).filter(Concern.status.in_(OPEN_CONCERN_STATUSES))
    open_concerns = open_q.count()
    critical_concerns = open_q.filter(Concern.priority == "critical").count()

    return {
        "total_projects": int(total_projects),
        "total_contracts": int(total_contracts),
        "ongoing_projects": int(ongoing_projects),
        "delayed_projects": int(delayed_projects),
        "pending_reports": int(pending_reports),
        "open_concerns": int(open_concerns),
        "critical_concerns": int(critical_concerns),
    }


def _safe_url(endpoint: str, **values) -> str:
    try:
        return url_for(endpoint, **values)
    except Exception:
        return "#"


def user_inbox(user, *, limit: int = 6) -> Dict[str, Any]:
    """Actionable items for the nav bell: pending reports + assigned/open concerns."""
    items: List[Dict[str, Any]] = []
    if not user or not getattr(user, "is_authenticated", False):
        return {"count": 0, "entries": items}

    pending = (
        scoped_daily_reports_query(user)
        .filter(DailyReport.status.in_(PENDING_REPORT_STATUSES))
        .order_by(DailyReport.report_date.desc(), DailyReport.id.desc())
        .limit(limit)
        .all()
    )
    for report in pending:
        items.append(
            {
                "kind": "daily_report",
                "title": f"گزارش روزانه در انتظار تأیید — {report.project.project_name if report.project else ''}",
                "meta": report.status_label,
                "url": _safe_url("daily_reports.detail", report_id=report.id),
                "tone": "orange",
            }
        )

    assigned = (
        visible_concerns_query(user)
        .filter(Concern.status.in_(OPEN_CONCERN_STATUSES))
        .filter(
            or_(
                Concern.assignee_id == user.id,
                Concern.priority == "critical",
            )
        )
        .order_by(Concern.priority.desc(), Concern.updated_at.desc())
        .limit(limit)
        .all()
    )
    for concern in assigned:
        items.append(
            {
                "kind": "concern",
                "title": concern.title,
                "meta": f"{concern.priority_label} · {concern.status_label}",
                "url": _safe_url("concerns.detail", concern_id=concern.id),
                "tone": "rose" if concern.priority == "critical" else "amber",
            }
        )

    # de-dupe by url, keep first
    seen = set()
    unique = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        unique.append(it)

    unique = unique[:limit]
    total = (
        scoped_daily_reports_query(user)
        .filter(DailyReport.status.in_(PENDING_REPORT_STATUSES))
        .count()
        + visible_concerns_query(user)
        .filter(Concern.status.in_(OPEN_CONCERN_STATUSES))
        .filter(or_(Concern.assignee_id == user.id, Concern.priority == "critical"))
        .count()
    )
    return {"count": int(total), "entries": unique}


def pending_reports_for_dashboard(user, *, limit: int = 5) -> List[DailyReport]:
    return (
        scoped_daily_reports_query(user)
        .filter(DailyReport.status.in_(PENDING_REPORT_STATUSES))
        .order_by(DailyReport.report_date.desc(), DailyReport.id.desc())
        .limit(limit)
        .all()
    )


def open_concerns_for_dashboard(user, *, limit: int = 5) -> List[Concern]:
    return (
        visible_concerns_query(user)
        .filter(Concern.status.in_(OPEN_CONCERN_STATUSES))
        .order_by(Concern.priority.desc(), Concern.updated_at.desc())
        .limit(limit)
        .all()
    )


def global_search(user, q: str, *, limit: int = 8) -> Dict[str, List[Dict[str, Any]]]:
    term = (q or "").strip()
    empty = {"projects": [], "daily_reports": [], "concerns": [], "query": term}
    if not term or len(term) < 2:
        return empty

    like = f"%{term}%"
    projects = (
        accessible_projects_query(user)
        .filter(
            or_(
                Project.project_name.ilike(like),
                Project.project_code.ilike(like),
                Project.client_name.ilike(like),
                Project.location.ilike(like),
            )
        )
        .order_by(Project.updated_at.desc())
        .limit(limit)
        .all()
    )
    reports = (
        scoped_daily_reports_query(user)
        .filter(
            or_(
                DailyReport.work_performed.ilike(like),
                DailyReport.issues_delays.ilike(like),
                DailyReport.notes.ilike(like),
                DailyReport.weather.ilike(like),
            )
        )
        .order_by(DailyReport.report_date.desc())
        .limit(limit)
        .all()
    )
    concerns = (
        visible_concerns_query(user)
        .filter(or_(Concern.title.ilike(like), Concern.description.ilike(like)))
        .order_by(Concern.updated_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "query": term,
        "projects": [
            {
                "id": p.id,
                "title": p.project_name,
                "meta": p.project_code,
                "url": _safe_url("projects.project_view", project_id=p.id),
            }
            for p in projects
        ],
        "daily_reports": [
            {
                "id": r.id,
                "title": f"گزارش {r.report_date} — {r.project.project_name if r.project else ''}",
                "meta": r.status_label,
                "url": _safe_url("daily_reports.detail", report_id=r.id),
            }
            for r in reports
        ],
        "concerns": [
            {
                "id": c.id,
                "title": c.title,
                "meta": f"{c.priority_label} · {c.status_label}",
                "url": _safe_url("concerns.detail", concern_id=c.id),
            }
            for c in concerns
        ],
    }
