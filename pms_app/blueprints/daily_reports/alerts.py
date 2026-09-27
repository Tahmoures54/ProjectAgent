from __future__ import annotations

from datetime import datetime, timedelta

from flask import abort, render_template, request
from flask_login import current_user

from pms_app.extensions import db
from pms_app.models.daily_report import DailyReportProgress
from pms_app.models.item import ContractItem
from pms_app.models.project import Project
from pms_app.utils.access import current_company_id as _company_id

from . import bp
from .routes import _accessible_projects


@bp.route("/control-alerts")
def control_alerts():
    """Action-oriented project-control alerts from approved progress history."""
    projects = _accessible_projects()
    accessible_ids = {p.id for p in projects}
    project_id = request.args.get("project_id", type=int)
    severity = request.args.get("severity", "").strip().lower()
    alert_type = request.args.get("type", "").strip().lower()

    if project_id and project_id not in accessible_ids:
        abort(403)
    if severity not in {"", "high", "medium", "low"}:
        severity = ""
    if alert_type not in {"", "suspicious", "decrease", "stale", "scope", "quantity"}:
        alert_type = ""

    query = DailyReportProgress.query
    if not current_user.is_owner:
        cid = _company_id()
        query = query.filter(DailyReportProgress.company_id == cid) if cid else query.filter(db.text("1=0"))
    query = query.filter(DailyReportProgress.project_id.in_(accessible_ids)) if accessible_ids else query.filter(db.text("1=0"))
    if project_id:
        query = query.filter(DailyReportProgress.project_id == project_id)

    rows = query.order_by(
        DailyReportProgress.project_id.asc(),
        DailyReportProgress.contract_item_id.asc(),
        DailyReportProgress.location.asc(),
        DailyReportProgress.structure_tag.asc(),
        DailyReportProgress.created_at.asc(),
        DailyReportProgress.id.asc(),
    ).limit(5000).all()

    project_map = {p.id: p for p in projects}
    item_ids = {r.contract_item_id for r in rows if r.contract_item_id}
    item_map = {i.id: i for i in ContractItem.query.filter(ContractItem.id.in_(item_ids)).all()} if item_ids else {}

    previous = {}
    latest = {}
    for row in rows:
        key = (row.project_id, row.contract_item_id, row.location or "", row.structure_tag or "")
        previous[row.id] = latest.get(key)
        latest[key] = row

    now = datetime.utcnow()
    stale_after = timedelta(days=3)
    alerts = []

    for row in latest.values():
        old = previous.get(row.id)
        current = float(row.progress_percent) if row.progress_percent is not None else None
        old_value = float(old.progress_percent) if old and old.progress_percent is not None else None
        delta = round(current - old_value, 2) if current is not None and old_value is not None else None
        age = now - row.created_at if row.created_at else None
        base = {
            "project": project_map.get(row.project_id),
            "item": item_map.get(row.contract_item_id),
            "row": row,
            "delta": delta,
            "age_days": age.days if age else None,
        }

        if current is None or (delta is not None and delta > 25):
            alerts.append({**base, "type": "suspicious", "severity": "high", "title": "Progress غیرعادی", "reason": "جهش بیش از ۲۵ واحد درصد یا مقدار Progress نامشخص است."})
        elif delta is not None and delta < 0:
            alerts.append({**base, "type": "decrease", "severity": "high", "title": "کاهش Progress", "reason": f"Progress نسبت به ثبت قبلی {abs(delta):g}% کاهش یافته است."})

        if row.quantity_done is not None and float(row.quantity_done) < 0:
            alerts.append({**base, "type": "quantity", "severity": "high", "title": "مقدار منفی", "reason": "Quantity Done منفی ثبت شده است."})

        if not (row.location or "").strip() or not (row.structure_tag or "").strip():
            alerts.append({**base, "type": "scope", "severity": "medium", "title": "Scope ناقص", "reason": "Location یا Structure Tag برای Progress ثبت نشده است."})

        if age and age > stale_after:
            alerts.append({**base, "type": "stale", "severity": "medium", "title": "Progress قدیمی", "reason": f"آخرین ثبت این Scope حدود {age.days} روز قبل بوده است."})

    if severity:
        alerts = [a for a in alerts if a["severity"] == severity]
    if alert_type:
        alerts = [a for a in alerts if a["type"] == alert_type]

    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 9), -(a["row"].created_at.timestamp() if a["row"].created_at else 0)))

    summary = {
        "total": len(alerts),
        "high": sum(a["severity"] == "high" for a in alerts),
        "medium": sum(a["severity"] == "medium" for a in alerts),
        "low": sum(a["severity"] == "low" for a in alerts),
    }
    return render_template(
        "daily_reports/control_alerts.html",
        alerts=alerts,
        summary=summary,
        projects=projects,
        project_id=project_id,
        severity=severity,
        alert_type=alert_type,
    )
