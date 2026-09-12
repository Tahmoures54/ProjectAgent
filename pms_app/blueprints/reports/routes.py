# Path: pms_app/blueprints/reports/routes.py
from __future__ import annotations

from flask import render_template
from flask_login import login_required

from pms_app.models.daily_report import DailyReport
from pms_app.models.project import Project
from pms_app.utils.access import scope_daily_reports_query, scope_projects_query
from pms_app.utils.security import permission_required

from . import bp


@bp.route("/reports")
@login_required
@permission_required("reports.read")
def reports():
    """
    Control-room hub for real reporting surfaces (daily reports + project EVM).
    Does not list the unused unscoped Report rows.
    """
    projects = (
        scope_projects_query(Project.query)
        .filter(Project.status == "active")
        .order_by(Project.updated_at.desc())
        .limit(8)
        .all()
    )
    pending_daily = (
        scope_daily_reports_query(DailyReport.query)
        .filter(DailyReport.status.in_(("submitted", "under_review")))
        .order_by(DailyReport.updated_at.desc())
        .limit(8)
        .all()
    )
    recent_daily = (
        scope_daily_reports_query(DailyReport.query)
        .order_by(DailyReport.report_date.desc(), DailyReport.id.desc())
        .limit(8)
        .all()
    )
    return render_template(
        "reports/reports.html",
        projects=projects,
        pending_daily=pending_daily,
        recent_daily=recent_daily,
    )
