from __future__ import annotations

from datetime import datetime, timedelta
import json

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from pms_app.extensions import db
from pms_app.models.action_item import ActionItem
from pms_app.models.daily_report import DailyReportProgress
from pms_app.models.item import ContractItem
from pms_app.models.project import Project
from pms_app.utils.access import current_company_id as _company_id

from . import bp
from .routes import _accessible_projects, can_manage_project_reports


ACTION_PREFIX = "PA-ALERT"
ACTION_STATES = {"open", "in_progress", "done", "cancelled"}


def _alert_key(alert_type: str, row_id: int) -> str:
    return f"{ACTION_PREFIX}:{alert_type}:{row_id}"


def _action_for(alert_type: str, row_id: int) -> ActionItem | None:
    key = _alert_key(alert_type, row_id)
    return ActionItem.query.filter(ActionItem.title.startswith(key)).order_by(ActionItem.id.desc()).first()


def _append_event(action: ActionItem, event: str, note: str = "") -> None:
    payload = []
    if action.description:
        try:
            payload = json.loads(action.description)
            if not isinstance(payload, list):
                payload = []
        except (TypeError, ValueError):
            payload = []
    payload.append({
        "event": event,
        "user_id": current_user.id,
        "at": datetime.utcnow().isoformat(timespec="seconds"),
        "note": note,
    })
    action.description = json.dumps(payload, ensure_ascii=False)


@bp.route("/control-alerts/action", methods=["POST"])
def control_alert_action():
    """Create or progress an actionable work item from a control alert."""
    project_id = request.form.get("project_id", type=int)
    row_id = request.form.get("row_id", type=int)
    alert_type = request.form.get("alert_type", "").strip().lower()
    command = request.form.get("command", "").strip().lower()
    assignee_id = request.form.get("assignee_id", type=int)
    note = request.form.get("note", "").strip()

    if not row_id or not project_id or not alert_type:
        abort(400)
    project = next((p for p in _accessible_projects() if p.id == project_id), None)
    if not project:
        abort(403)
    if not can_manage_project_reports(project):
        abort(403)

    row = DailyReportProgress.query.filter_by(id=row_id, project_id=project_id).first_or_404()
    action = _action_for(alert_type, row.id)

    if command == "create":
        if action:
            flash("برای این هشدار قبلاً Action ساخته شده است.", "info")
        else:
            title = f"{_alert_key(alert_type, row.id)} | کنترل هشدار {alert_type} | {row.location or 'بدون Location'} | {row.structure_tag or 'بدون Tag'}"
            action = ActionItem(
                company_id=row.company_id or _company_id(),
                project_id=project_id,
                contract_item_id=row.contract_item_id,
                title=title[:250],
                status="open",
                priority="critical" if alert_type in {"suspicious", "decrease", "quantity"} else "high",
                assignee_id=assignee_id,
                created_by_id=current_user.id,
                progress_percent=0,
            )
            db.session.add(action)
            db.session.flush()
            _append_event(action, "created", note)
            db.session.commit()
            flash("Action برای هشدار ایجاد شد.", "success")
    elif command in {"start", "resolve", "close", "cancel"}:
        if not action:
            flash("ابتدا برای این هشدار Action ایجاد کنید.", "warning")
        else:
            transitions = {
                "start": "in_progress",
                "resolve": "done",
                "close": "done",
                "cancel": "cancelled",
            }
            new_status = transitions[command]
            action.status = new_status
            if assignee_id:
                action.assignee_id = assignee_id
            if new_status == "done":
                action.mark_done()
            _append_event(action, command, note)
            db.session.commit()
            flash("وضعیت Action به‌روزرسانی شد.", "success")
    else:
        abort(400)

    return redirect(url_for(
        "daily_reports.control_alerts",
        project_id=project_id,
        severity=request.form.get("severity", ""),
        type=request.form.get("filter_type", ""),
    ))


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
        base = {"project": project_map.get(row.project_id), "item": item_map.get(row.contract_item_id), "row": row, "delta": delta, "age_days": age.days if age else None}

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

    action_rows = [a for a in alerts if a.get("row")]
    action_ids = {a["row"].id for a in action_rows}
    actions = ActionItem.query.filter(ActionItem.project_id.in_(accessible_ids), ActionItem.title.like(f"{ACTION_PREFIX}:%")).all() if action_ids else []
    action_map = {}
    for action in actions:
        parts = action.title.split("|")[0].split(":")
        if len(parts) == 3:
            action_map[parts[2]] = action
    for alert in alerts:
        alert["action"] = action_map.get(str(alert["row"].id))

    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 9), -(a["row"].created_at.timestamp() if a["row"].created_at else 0)))
    summary = {"total": len(alerts), "high": sum(a["severity"] == "high" for a in alerts), "medium": sum(a["severity"] == "medium" for a in alerts), "low": sum(a["severity"] == "low" for a in alerts)}
    return render_template("daily_reports/control_alerts.html", alerts=alerts, summary=summary, projects=projects, project_id=project_id, severity=severity, alert_type=alert_type)
