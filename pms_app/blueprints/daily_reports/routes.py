# Path: pms_app/blueprints/daily_reports/routes.py
from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from pms_app.extensions import db
from pms_app.models.daily_report import DailyReport, DailyReportHistory, DailyReportProgress
from pms_app.models.item import ContractItem
from pms_app.models.action_item import ActionItem
from pms_app.models.project import Project
from pms_app.models.project_membership import ProjectMembership
from pms_app.utils.excel_io import workbook_to_bytes, xlsx_response
from pms_app.utils.notify import notify_daily_report_decision, notify_daily_report_submitted
from pms_app.utils.security import ensure_rbac_seed
from pms_app.utils.access import (
    current_company_id as _company_id,
    get_project_or_403,
    scope_daily_reports_query as scope_reports_query,
)

from . import bp
from .excel import (
    build_template_workbook,
    dumps_rows,
    export_reports_workbook,
    export_progress_traceability_workbook,
    import_daily_reports_from_workbook,
)
from .forms import ApplyProgressForm, ControlAlertActionForm, DailyReportForm, ImportExcelForm, ReviewForm


def _parse_lines_to_list(raw: str, expected_parts: int = 2) -> List[dict]:
    result = []
    if not raw:
        return result
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace("|", ",").split(",") if p.strip()]
        if len(parts) < 1:
            continue
        if expected_parts == 2:
            result.append({"role": parts[0], "count": _safe_int(parts[1] if len(parts) > 1 else 0)})
        elif expected_parts == 3:
            result.append(
                {
                    "name": parts[0],
                    "count": _safe_int(parts[1] if len(parts) > 1 else 1),
                    "hours": _safe_float(parts[2] if len(parts) > 2 else 0),
                }
            )
        elif expected_parts == 6:
            result.append(
                {
                    "contract_item_id": _safe_int(parts[0]),
                    "progress_percent": _safe_float(parts[1] if len(parts) > 1 else None),
                    "quantity_done": _safe_float(parts[2] if len(parts) > 2 else None),
                    "location": parts[3] if len(parts) > 3 else "",
                    "structure_tag": parts[4] if len(parts) > 4 else "",
                    "notes": parts[5] if len(parts) > 5 else "",
                }
            )
    return result


def _safe_int(v) -> Optional[int]:
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return None


def _safe_float(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def _list_to_raw(items: Optional[list], keys: List[str]) -> str:
    if not items:
        return "[]"
    return dumps_rows(items)


def _parse_structured(raw: str, kind: str) -> List[dict]:
    text = (raw or "").strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            rows = []
            for it in data:
                if not isinstance(it, dict):
                    continue
                if kind == "manpower":
                    role = it.get("role") or it.get("name")
                    if not role:
                        continue
                    rows.append({"role": str(role), "count": _safe_int(it.get("count")) or 0})
                elif kind == "equipment":
                    name = it.get("name")
                    if not name:
                        continue
                    rows.append(
                        {
                            "name": str(name),
                            "count": _safe_int(it.get("count")) or 1,
                            "hours": _safe_float(it.get("hours")) or 0,
                        }
                    )
                elif kind == "progress":
                    rows.append(
                        {
                            "contract_item_id": _safe_int(it.get("contract_item_id") or it.get("id")),
                            "progress_percent": _safe_float(it.get("progress_percent")),
                            "quantity_done": _safe_float(it.get("quantity_done")),
                            "location": str(it.get("location") or it.get("work_area") or "").strip(),
                            "structure_tag": str(it.get("structure_tag") or it.get("tag") or "").strip(),
                            "notes": it.get("notes") or "",
                            "wbs_code": it.get("wbs_code") or "",
                        }
                    )
                elif kind == "materials":
                    name = it.get("name")
                    if not name:
                        continue
                    rows.append(
                        {
                            "name": str(name),
                            "qty": _safe_float(it.get("qty") or it.get("quantity")),
                            "unit": it.get("unit") or "",
                            "vendor": it.get("vendor") or "",
                        }
                    )
                elif kind == "engineering":
                    title = it.get("title") or it.get("doc_no")
                    if not title:
                        continue
                    rows.append(
                        {
                            "doc_no": str(it.get("doc_no") or ""),
                            "title": str(it.get("title") or title),
                            "status": str(it.get("status") or ""),
                        }
                    )
            return rows
    expected = {"manpower": 2, "equipment": 3, "progress": 6, "materials": 4, "engineering": 3}.get(kind, 2)
    parsed = _parse_lines_to_list(text, expected)
    if kind == "materials":
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.replace("|", ",").split(",") if p.strip()]
            if not parts:
                continue
            out.append(
                {
                    "name": parts[0],
                    "qty": _safe_float(parts[1] if len(parts) > 1 else None),
                    "unit": parts[2] if len(parts) > 2 else "",
                    "vendor": parts[3] if len(parts) > 3 else "",
                }
            )
        return out
    if kind == "engineering":
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.replace("|", ",").split(",") if p.strip()]
            if not parts:
                continue
            out.append(
                {
                    "doc_no": parts[0] if len(parts) > 1 else "",
                    "title": parts[1] if len(parts) > 1 else parts[0],
                    "status": parts[2] if len(parts) > 2 else "",
                }
            )
        return out
    return parsed


def _project_items(project: Project) -> List[dict]:
    rows = []
    for contract in project.contracts:
        for item in contract.items.order_by(ContractItem.wbs_code.asc(), ContractItem.id.asc()).limit(400):
            rows.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "wbs": item.wbs_code or item.pms_item_number or "",
                    "progress": float(item.actual_progress_percentage or 0),
                    "discipline": item.discipline or item.l4_discipline or "",
                }
            )
    return rows


def _accessible_projects() -> List[Project]:
    if current_user.is_owner:
        return Project.query.filter_by(status="active").order_by(Project.project_name).limit(100).all()
    cid = _company_id()
    if not cid:
        return []
    base = Project.query.filter_by(company_id=cid, status="active")
    if not current_user.is_company_admin:
        base = (
            base.join(ProjectMembership)
            .filter(ProjectMembership.user_id == current_user.id)
            .filter(ProjectMembership.status == "active")
        )
    return base.order_by(Project.project_name).limit(100).all()


def _apply_form_to_report(report: DailyReport, form: DailyReportForm) -> None:
    report.report_date = form.report_date.data
    report.weather = form.weather.data or None
    report.temperature_min = form.temperature_min.data
    report.temperature_max = form.temperature_max.data
    report.manpower_total = form.manpower_total.data or 0
    report.manpower_details = _parse_structured(form.manpower_details_raw.data or "", "manpower")
    report.equipment_details = _parse_structured(form.equipment_details_raw.data or "", "equipment")
    report.work_performed = form.work_performed.data or None
    report.progress_updates = _parse_structured(form.progress_updates_raw.data or "", "progress")
    report.issues_delays = form.issues_delays.data or None
    report.hse_incidents = form.hse_incidents.data or None
    report.hse_observations = form.hse_observations.data or None
    report.near_miss_count = form.near_miss_count.data or 0
    report.visitors_meetings = form.visitors_meetings.data or None
    report.notes = form.notes.data or None
    report.epc_phase = form.epc_phase.data or None
    report.work_area = form.work_area.data or None
    report.shift = form.shift.data or None
    report.lost_time_hours = form.lost_time_hours.data
    report.materials_received = _parse_structured(form.materials_received_raw.data or "", "materials")
    report.engineering_outputs = _parse_structured(form.engineering_outputs_raw.data or "", "engineering")
    if report.manpower_details and not report.manpower_total:
        report.manpower_total = sum(int(x.get("count") or 0) for x in report.manpower_details)


def _hydrate_form(form: DailyReportForm, report: DailyReport) -> None:
    form.manpower_details_raw.data = dumps_rows(report.manpower_details)
    form.equipment_details_raw.data = dumps_rows(report.equipment_details)
    form.progress_updates_raw.data = dumps_rows(report.progress_updates)
    form.materials_received_raw.data = dumps_rows(report.materials_received)
    form.engineering_outputs_raw.data = dumps_rows(report.engineering_outputs)


def can_manage_project_reports(project: Project) -> bool:
    if not current_user.can_access_project(project):
        return False
    if current_user.is_owner or current_user.is_company_admin:
        return True
    membership = ProjectMembership.query.filter_by(
        project_id=project.id, user_id=current_user.id, status="active"
    ).first()
    return bool(membership and membership.role in ("admin", "manager"))


def can_submit_for_project(project: Project) -> bool:
    if not current_user.can_access_project(project):
        return False
    if current_user.is_owner or current_user.is_company_admin:
        return True
    if current_user.has_permission("daily_reports.create"):
        return True
    membership = ProjectMembership.query.filter_by(
        project_id=project.id, user_id=current_user.id, status="active"
    ).first()
    return bool(membership)


def get_report_or_403(report_id: int) -> DailyReport:
    report = db.session.get(DailyReport, report_id)
    if not report:
        abort(404)
    project = report.project
    if project is None:
        abort(404)
    if report.company_id and project.company_id and int(report.company_id) != int(project.company_id):
        abort(404)
    if not current_user.can_access_project(project):
        abort(403)
    return report


@bp.before_request
@login_required
def _guard():
    ensure_rbac_seed(update_existing=True)
    if not getattr(current_user, "is_active", True):
        flash("حساب شما غیرفعال است.", "danger")
        return redirect(url_for("main.dashboard"))


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    project_id = request.args.get("project_id", type=int)

    query = scope_reports_query(DailyReport.query)

    if project_id:
        query = query.filter(DailyReport.project_id == project_id)
    if status:
        query = query.filter(DailyReport.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                DailyReport.work_performed.ilike(like),
                DailyReport.issues_delays.ilike(like),
                DailyReport.notes.ilike(like),
            )
        )

    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("PER_PAGE", 20)
    pagination = query.order_by(
        DailyReport.report_date.desc(), DailyReport.id.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    projects = _accessible_projects()

    return render_template(
        "daily_reports/list.html",
        reports=pagination.items,
        pagination=pagination,
        q=q,
        status=status,
        project_id=project_id,
        projects=projects,
        status_labels=DailyReport.STATUS_LABELS,
        can_create=bool(projects),
    )


@bp.route("/control-alerts/action", methods=["POST"])
def control_alert_action():
    project_id = request.form.get("project_id", type=int)
    row_id = request.form.get("row_id", type=int)
    typ = request.form.get("alert_type", "").strip()
    command = request.form.get("command", "").strip()
    form = ControlAlertActionForm()
    if not form.validate_on_submit():
        abort(400, description="درخواست Alert نامعتبر است.")
    project = get_project_or_403(project_id)
    if not can_submit_for_project(project):
        abort(403)
    row = DailyReportProgress.query.filter_by(id=row_id, project_id=project.id).first_or_404()

    if command == "create":
        title_map = {
            "suspicious": "بررسی Progress غیرعادی",
            "decrease": "بررسی کاهش Progress",
            "stale": "به‌روزرسانی Progress قدیمی",
            "scope": "تکمیل Scope Progress",
            "quantity": "اصلاح Quantity منفی",
        }
        title = title_map.get(typ, "بررسی هشدار کنترل پروژه")
        marker = f"Progress Alert row={row.id} type={typ}"
        action = (
            ActionItem.query
            .filter_by(project_id=project.id, contract_item_id=row.contract_item_id)
            .filter(ActionItem.description.ilike(f"%{marker}%"))
            .first()
        )
        if not action:
            action = ActionItem(
                company_id=project.company_id, project_id=project.id,
                contract_item_id=row.contract_item_id, title=title,
                description=f"{marker} | location={row.location or '-'} | tag={row.structure_tag or '-'}",
                status="open", priority="critical" if typ in ("suspicious", "decrease", "quantity") else "high",
                created_by_id=current_user.id,
            )
            db.session.add(action)
            db.session.flush()
            action.add_history(user_id=current_user.id, action="created", to_status="open", note=marker)
            flash("هشدار به Action تبدیل شد.", "success")
        else:
            flash("برای این هشدار Action قبلاً ایجاد شده است.", "info")
    elif command in {"start", "resolve"}:
        action = (
            ActionItem.query
            .filter_by(project_id=project.id, contract_item_id=row.contract_item_id)
            .filter(ActionItem.description.ilike(f"%Progress Alert row={row.id} type={typ}%"))
            .order_by(ActionItem.id.desc()).first()
        )
        if not action:
            flash("ابتدا Action هشدار را ایجاد کنید.", "warning")
        else:
            old = action.status
            if command == "start" and old not in ("done", "cancelled"):
                action.status = "in_progress"
                action.add_history(user_id=current_user.id, action="status_change", from_status=old, to_status="in_progress")
                flash("Action وارد مرحله بررسی شد.", "success")
            elif command == "resolve" and old not in ("done", "cancelled"):
                action.mark_done(current_user.id, "حل هشدار کنترل پروژه")
                flash("هشدار حل‌شده ثبت شد.", "success")
    else:
        abort(400)
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطا در ذخیره Action.", "danger")
    return redirect(url_for("daily_reports.control_alerts", project_id=project.id))


@bp.route("/progress-traceability")
def progress_traceability():
    """گزارش ردیابی Progress اعمال‌شده بر اساس پروژه، WBS، لوکیشن و تگ سازه."""
    project_id = request.args.get("project_id", type=int)
    item_id = request.args.get("item_id", type=int)
    location = request.args.get("location", "").strip()
    structure_tag = request.args.get("structure_tag", "").strip()
    date_from_raw = request.args.get("date_from", "").strip()
    date_to_raw = request.args.get("date_to", "").strip()
    quality = request.args.get("quality", "").strip().lower()
    if quality not in {"", "suspicious", "decrease"}:
        quality = ""

    projects = _accessible_projects()
    accessible_ids = {p.id for p in projects}
    if project_id and project_id not in accessible_ids:
        abort(403)

    query = db.session.query(DailyReportProgress).join(DailyReport, DailyReportProgress.report_id == DailyReport.id).join(Project, DailyReportProgress.project_id == Project.id)
    if not current_user.is_owner:
        cid = _company_id()
        if not cid:
            query = query.filter(db.text("1=0"))
        else:
            query = query.filter(DailyReportProgress.company_id == cid)
    if accessible_ids:
        query = query.filter(DailyReportProgress.project_id.in_(accessible_ids))
    else:
        query = query.filter(db.text("1=0"))
    if project_id:
        query = query.filter(DailyReportProgress.project_id == project_id)
    if item_id:
        query = query.filter(DailyReportProgress.contract_item_id == item_id)
    if location:
        query = query.filter(DailyReportProgress.location.ilike("%" + location + "%"))
    if structure_tag:
        query = query.filter(DailyReportProgress.structure_tag.ilike("%" + structure_tag + "%"))

    try:
        if date_from_raw:
            query = query.filter(DailyReport.report_date >= date.fromisoformat(date_from_raw))
        if date_to_raw:
            query = query.filter(DailyReport.report_date <= date.fromisoformat(date_to_raw))
    except ValueError:
        flash("بازه تاریخ نامعتبر است.", "warning")

    query = query.order_by(DailyReport.report_date.desc(), DailyReportProgress.created_at.desc(), DailyReportProgress.id.desc())

    # Quality filters require the previous record, so resolve them from the
    # complete filtered history before pagination. Cap this safety scan to
    # the same 5000-row ceiling used by Excel export.
    if quality:
        quality_candidates = query.limit(5000).all()
        matching_ids = []
        for candidate in quality_candidates:
            previous = (
                DailyReportProgress.query
                .filter(
                    DailyReportProgress.project_id == candidate.project_id,
                    DailyReportProgress.contract_item_id == candidate.contract_item_id,
                    DailyReportProgress.location == candidate.location,
                    DailyReportProgress.structure_tag == candidate.structure_tag,
                    DailyReportProgress.created_at < candidate.created_at,
                )
                .order_by(DailyReportProgress.created_at.desc(), DailyReportProgress.id.desc())
                .first()
            )
            current = float(candidate.progress_percent) if candidate.progress_percent is not None else None
            old_value = float(previous.progress_percent) if previous and previous.progress_percent is not None else None
            delta = None if current is None or old_value is None else round(current - old_value, 2)
            suspicious = (
                current is None
                or (delta is not None and (delta < 0 or delta > 25))
                or (candidate.quantity_done is not None and float(candidate.quantity_done) < 0)
            )
            if (quality == "suspicious" and suspicious) or (quality == "decrease" and delta is not None and delta < 0):
                matching_ids.append(candidate.id)
        query = query.filter(DailyReportProgress.id.in_(matching_ids)) if matching_ids else query.filter(db.text("1=0"))

    # KPI summary uses the exact same access-control and filters as the table.
    summary_row = query.with_entities(
        func.count(DailyReportProgress.id),
        func.count(func.distinct(DailyReportProgress.contract_item_id)),
        func.count(func.distinct(DailyReportProgress.structure_tag)),
        func.max(DailyReport.report_date),
        func.max(DailyReportProgress.progress_percent),
        func.sum(DailyReportProgress.quantity_done),
    ).first()
    traceability_summary = {
        "records": int(summary_row[0] or 0),
        "items": int(summary_row[1] or 0),
        "tags": int(summary_row[2] or 0),
        "latest_date": summary_row[3],
        "max_progress": summary_row[4],
        "total_quantity": summary_row[5],
    }
    location_summary = (
        query.with_entities(DailyReportProgress.location, func.count(DailyReportProgress.id).label("records"))
        .filter(DailyReportProgress.location.isnot(None), DailyReportProgress.location != "")
        .group_by(DailyReportProgress.location)
        .order_by(func.count(DailyReportProgress.id).desc(), DailyReportProgress.location.asc())
        .limit(8).all()
    )
    tag_summary = (
        query.with_entities(DailyReportProgress.structure_tag, func.count(DailyReportProgress.id).label("records"))
        .filter(DailyReportProgress.structure_tag.isnot(None), DailyReportProgress.structure_tag != "")
        .group_by(DailyReportProgress.structure_tag)
        .order_by(func.count(DailyReportProgress.id).desc(), DailyReportProgress.structure_tag.asc())
        .limit(8).all()
    )

    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("PER_PAGE", 20)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    trace_rows = []
    quality_counts = {"increase": 0, "unchanged": 0, "decrease": 0, "suspicious": 0, "baseline": 0}
    for row in pagination.items:
        previous = (
            DailyReportProgress.query
            .filter(
                DailyReportProgress.project_id == row.project_id,
                DailyReportProgress.contract_item_id == row.contract_item_id,
                DailyReportProgress.location == row.location,
                DailyReportProgress.structure_tag == row.structure_tag,
                DailyReportProgress.created_at < row.created_at,
            )
            .order_by(DailyReportProgress.created_at.desc(), DailyReportProgress.id.desc())
            .first()
        )
        current = float(row.progress_percent) if row.progress_percent is not None else None
        old_value = float(previous.progress_percent) if previous and previous.progress_percent is not None else None
        if current is None or old_value is None:
            change, delta = "baseline", None
        else:
            delta = round(current - old_value, 2)
            change = "increase" if delta > 0 else ("decrease" if delta < 0 else "unchanged")
        suspicious = (
            current is None
            or (delta is not None and (delta < 0 or delta > 25))
            or (row.quantity_done is not None and float(row.quantity_done) < 0)
        )
        quality_counts[change] += 1
        if suspicious:
            quality_counts["suspicious"] += 1
        trace_rows.append({
            "row": row, "previous_progress": old_value,
            "delta": delta, "change": change, "suspicious": suspicious,
        })

    quality_summary = {
        "increase": quality_counts["increase"],
        "unchanged": quality_counts["unchanged"],
        "decrease": quality_counts["decrease"],
        "baseline": quality_counts["baseline"],
        "suspicious": quality_counts["suspicious"],
    }

    item_ids = {r.contract_item_id for r in pagination.items}
    items = {item.id: item for item in ContractItem.query.filter(ContractItem.id.in_(item_ids)).all()} if item_ids else {}
    return render_template(
        "daily_reports/progress_traceability.html",
        rows=trace_rows, pagination=pagination, projects=projects,
        project_id=project_id, item_id=item_id, location=location,
        structure_tag=structure_tag, date_from=date_from_raw, date_to=date_to_raw, quality=quality,
        items=items, traceability_summary=traceability_summary,
        location_summary=location_summary, tag_summary=tag_summary, quality_summary=quality_summary,
    )

@bp.route("/project/<int:project_id>")
def project_list(project_id: int):
    project = get_project_or_403(project_id)
    status = request.args.get("status", "").strip()
    query = DailyReport.query.filter_by(project_id=project.id)
    if status:
        query = query.filter_by(status=status)
    reports = query.order_by(DailyReport.report_date.desc()).limit(50).all()
    can_submit = can_submit_for_project(project)
    can_approve = can_manage_project_reports(project)
    return render_template(
        "daily_reports/project_list.html",
        project=project,
        reports=reports,
        status=status,
        can_submit=can_submit,
        can_approve=can_approve,
        status_labels=DailyReport.STATUS_LABELS,
        import_form=ImportExcelForm(),
    )


@bp.route("/project/<int:project_id>/new", methods=["GET", "POST"])
def create(project_id: int):
    project = get_project_or_403(project_id)
    if not can_submit_for_project(project):
        flash("شما مجوز ثبت گزارش روزانه برای این پروژه را ندارید.", "danger")
        return redirect(url_for("daily_reports.project_list", project_id=project_id))

    form = DailyReportForm()
    if form.validate_on_submit():
        report = DailyReport(
            company_id=project.company_id,
            project_id=project.id,
            submitted_by_id=current_user.id,
            status="draft",
        )
        _apply_form_to_report(report, form)
        db.session.add(report)
        try:
            db.session.flush()
            report.add_history(
                user_id=current_user.id,
                action="create",
                from_status=None,
                to_status="draft",
                comment="ایجاد گزارش روزانه",
            )
            action = (
                request.form.get("form_action")
                or request.form.get("action")
                or form.action.data
                or "save"
            ).strip().lower()
            if action == "submit":
                report.submit(current_user.id)
            db.session.commit()
            if action == "submit":
                notify_daily_report_submitted(report)
                flash("گزارش روزانه با موفقیت ثبت و برای تأیید ارسال شد.", "success")
            else:
                flash("پیش‌نویس گزارش ذخیره شد.", "success")
            return redirect(url_for("daily_reports.detail", report_id=report.id))
        except IntegrityError:
            db.session.rollback()
            flash("برای این تاریخ و کاربر قبلاً گزارشی ثبت شده است.", "warning")
        except SQLAlchemyError:
            db.session.rollback()
            flash("خطای پایگاه داده هنگام ذخیره گزارش.", "danger")

    return render_template(
        "daily_reports/form.html",
        form=form,
        project=project,
        title="ثبت گزارش روزانه جدید",
        report=None,
        contract_items=_project_items(project),
        import_form=ImportExcelForm(),
    )


@bp.route("/<int:report_id>")
def detail(report_id: int):
    report = get_report_or_403(report_id)
    can_edit = report.is_editable and (
        report.submitted_by_id == current_user.id
        or current_user.is_owner
        or current_user.is_company_admin
    )
    can_manage = can_manage_project_reports(report.project)
    can_approve = report.is_pending_approval and can_manage
    history = report.history.order_by(DailyReportHistory.created_at.asc()).all()
    review_form = ReviewForm() if can_approve else None
    apply_progress_form = ApplyProgressForm() if can_manage and report.progress_application_status == "approved_not_applied" else None
    return render_template(
        "daily_reports/detail.html",
        report=report,
        history=history,
        can_edit=can_edit,
        can_approve=can_approve,
        can_manage=can_manage,
        review_form=review_form,
        apply_progress_form=apply_progress_form,
        status_labels=DailyReport.STATUS_LABELS,
    )


@bp.route("/<int:report_id>/edit", methods=["GET", "POST"])
def edit(report_id: int):
    report = get_report_or_403(report_id)
    if not report.is_editable:
        flash("این گزارش قابل ویرایش نیست (وضعیت نهایی یا در حال بررسی).", "warning")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    if report.submitted_by_id != current_user.id and not (
        current_user.is_owner or current_user.is_company_admin
    ):
        flash("فقط ارسال‌کننده یا مدیران می‌توانند این گزارش را ویرایش کنند.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))

    form = DailyReportForm(obj=report)
    if request.method == "GET":
        _hydrate_form(form, report)

    if form.validate_on_submit():
        _apply_form_to_report(report, form)

        action = (
            request.form.get("form_action")
            or request.form.get("action")
            or form.action.data
            or "save"
        ).strip().lower()
        try:
            if action == "submit":
                report.submit(current_user.id)
                flash("گزارش ویرایش و برای تأیید ارسال شد.", "success")
            else:
                report.add_history(
                    user_id=current_user.id,
                    action="update",
                    from_status=report.status,
                    to_status=report.status,
                    comment="ویرایش پیش‌نویس",
                )
                flash("گزارش ذخیره شد.", "success")
            db.session.commit()
            if action == "submit":
                notify_daily_report_submitted(report)
            return redirect(url_for("daily_reports.detail", report_id=report.id))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
        except SQLAlchemyError:
            db.session.rollback()
            flash("خطای پایگاه داده.", "danger")

    return render_template(
        "daily_reports/form.html",
        form=form,
        project=report.project,
        title="ویرایش گزارش روزانه",
        report=report,
        contract_items=_project_items(report.project),
        import_form=ImportExcelForm(),
    )


@bp.route("/<int:report_id>/review", methods=["POST"])
def review(report_id: int):
    report = get_report_or_403(report_id)
    if not can_manage_project_reports(report.project):
        flash("شما مجوز تأیید/رد گزارش این پروژه را ندارید.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    if not report.is_pending_approval:
        flash("این گزارش در وضعیت قابل بررسی نیست.", "warning")
        return redirect(url_for("daily_reports.detail", report_id=report_id))

    form = ReviewForm()
    if not form.validate_on_submit():
        flash("فرم بررسی نامعتبر است.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))

    action = form.action.data
    comment = (form.comment.data or "").strip()
    apply_progress = form.apply_progress.data == "yes"

    try:
        if action == "approve":
            report.approve(current_user.id, comment=comment or None, apply_progress=apply_progress)
            flash("گزارش با موفقیت تأیید شد" + (" و پیشرفت آیتم‌ها اعمال گردید." if apply_progress else "."), "success")
        elif action == "reject":
            report.reject(current_user.id, comment)
            flash("گزارش رد شد.", "info")
        elif action == "request_revision":
            report.request_revision(current_user.id, comment)
            flash("درخواست اصلاح برای ارسال‌کننده ثبت شد.", "warning")
        else:
            flash("عملیات نامعتبر.", "danger")
            return redirect(url_for("daily_reports.detail", report_id=report_id))
        db.session.commit()
        notify_daily_report_decision(report, decision=action)
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطای پایگاه داده هنگام بررسی گزارش.", "danger")

    return redirect(url_for("daily_reports.detail", report_id=report_id))


@bp.route("/<int:report_id>/apply-progress", methods=["POST"])
def apply_progress(report_id: int):
    report = get_report_or_403(report_id)
    if not can_manage_project_reports(report.project):
        flash("شما مجوز اعمال پیشرفت این پروژه را ندارید.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    form = ApplyProgressForm()
    if not form.validate_on_submit():
        flash("درخواست اعمال پیشرفت نامعتبر است.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    try:
        # PostgreSQL row-level lock makes the idempotency check safe against
        # concurrent apply-progress requests. SQLite ignores FOR UPDATE.
        locked_report = (
            DailyReport.query.filter(DailyReport.id == report_id)
            .with_for_update()
            .first()
        )
        if locked_report is None:
            abort(404)
        if not can_manage_project_reports(locked_report.project):
            abort(403)
        locked_report.apply_approved_progress()
        db.session.commit()
        flash("پیشرفت گزارش با موفقیت روی آیتم‌ها اعمال شد.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "warning")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطای پایگاه داده هنگام اعمال پیشرفت.", "danger")
    return redirect(url_for("daily_reports.detail", report_id=report_id))


@bp.route("/<int:report_id>/submit", methods=["POST"])
def submit(report_id: int):
    report = get_report_or_403(report_id)
    if report.submitted_by_id != current_user.id and not (
        current_user.is_owner or current_user.is_company_admin
    ):
        flash("فقط ارسال‌کننده می‌تواند گزارش را ارسال کند.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    try:
        report.submit(current_user.id)
        db.session.commit()
        notify_daily_report_submitted(report)
        flash("گزارش برای تأیید ارسال شد.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطا در ارسال گزارش.", "danger")
    return redirect(url_for("daily_reports.detail", report_id=report_id))


@bp.route("/<int:report_id>/delete", methods=["POST"])
def delete(report_id: int):
    report = get_report_or_403(report_id)
    if report.status not in ("draft", "needs_revision", "rejected"):
        flash("فقط پیش‌نویس، نیازمند اصلاح یا ردشده قابل حذف است.", "warning")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    if report.submitted_by_id != current_user.id and not (
        current_user.is_owner or current_user.is_company_admin
    ):
        flash("مجوز حذف ندارید.", "danger")
        return redirect(url_for("daily_reports.detail", report_id=report_id))
    project_id = report.project_id
    try:
        db.session.delete(report)
        db.session.commit()
        flash("گزارش حذف شد.", "info")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطا در حذف.", "danger")
    return redirect(url_for("daily_reports.project_list", project_id=project_id))


def _all_contract_items(project: Project) -> List[ContractItem]:
    items: List[ContractItem] = []
    for contract in project.contracts:
        rel = getattr(contract, "items", None)
        if rel is None:
            continue
        try:
            items.extend(rel.order_by(ContractItem.wbs_code.asc(), ContractItem.id.asc()).limit(500).all())
        except Exception:
            items.extend(list(rel)[:500])
    return items


@bp.route("/progress-traceability/export.xlsx")
def progress_traceability_export():
    """Export the same tenant-scoped Progress Traceability view to Excel."""
    project_id = request.args.get("project_id", type=int)
    item_id = request.args.get("item_id", type=int)
    location = request.args.get("location", "").strip()
    structure_tag = request.args.get("structure_tag", "").strip()
    date_from_raw = request.args.get("date_from", "").strip()
    date_to_raw = request.args.get("date_to", "").strip()
    quality = request.args.get("quality", "").strip().lower()
    if quality not in {"", "suspicious", "decrease"}:
        quality = ""

    projects = _accessible_projects()
    accessible_ids = {p.id for p in projects}
    if project_id and project_id not in accessible_ids:
        abort(403)

    query = (
        db.session.query(DailyReportProgress)
        .join(DailyReport, DailyReportProgress.report_id == DailyReport.id)
        .join(Project, DailyReportProgress.project_id == Project.id)
    )
    if not current_user.is_owner:
        cid = _company_id()
        query = query.filter(
            DailyReportProgress.company_id == cid if cid else db.text("1=0")
        )
    query = query.filter(
        DailyReportProgress.project_id.in_(accessible_ids)
        if accessible_ids else db.text("1=0")
    )
    if project_id:
        query = query.filter(DailyReportProgress.project_id == project_id)
    if item_id:
        query = query.filter(DailyReportProgress.contract_item_id == item_id)
    if location:
        query = query.filter(DailyReportProgress.location.ilike("%" + location + "%"))
    if structure_tag:
        query = query.filter(DailyReportProgress.structure_tag.ilike("%" + structure_tag + "%"))
    try:
        if date_from_raw:
            query = query.filter(DailyReport.report_date >= date.fromisoformat(date_from_raw))
        if date_to_raw:
            query = query.filter(DailyReport.report_date <= date.fromisoformat(date_to_raw))
    except ValueError:
        abort(400, description="بازه تاریخ نامعتبر است.")

    if quality:
        candidates = query.order_by(
            DailyReport.report_date.desc(),
            DailyReportProgress.created_at.desc(),
            DailyReportProgress.id.desc(),
        ).limit(5000).all()
        matching_ids = []
        for candidate in candidates:
            previous = (
                DailyReportProgress.query
                .filter(
                    DailyReportProgress.project_id == candidate.project_id,
                    DailyReportProgress.contract_item_id == candidate.contract_item_id,
                    DailyReportProgress.location == candidate.location,
                    DailyReportProgress.structure_tag == candidate.structure_tag,
                    DailyReportProgress.created_at < candidate.created_at,
                )
                .order_by(DailyReportProgress.created_at.desc(), DailyReportProgress.id.desc())
                .first()
            )
            current = float(candidate.progress_percent) if candidate.progress_percent is not None else None
            old_value = float(previous.progress_percent) if previous and previous.progress_percent is not None else None
            delta = None if current is None or old_value is None else round(current - old_value, 2)
            suspicious = (
                current is None
                or (delta is not None and (delta < 0 or delta > 25))
                or (candidate.quantity_done is not None and float(candidate.quantity_done) < 0)
            )
            if (quality == "suspicious" and suspicious) or (quality == "decrease" and delta is not None and delta < 0):
                matching_ids.append(candidate.id)
        query = query.filter(DailyReportProgress.id.in_(matching_ids)) if matching_ids else query.filter(db.text("1=0"))

    rows = query.order_by(
        DailyReport.report_date.desc(),
        DailyReportProgress.created_at.desc(),
        DailyReportProgress.id.desc(),
    ).limit(5000).all()

    # Keep the export filter intact, but resolve the previous record from
    # the complete tenant/project history so date/tag filters cannot create
    # a false "first record".
    for row in rows:
        previous = (
            DailyReportProgress.query
            .filter(
                DailyReportProgress.project_id == row.project_id,
                DailyReportProgress.contract_item_id == row.contract_item_id,
                DailyReportProgress.location == row.location,
                DailyReportProgress.structure_tag == row.structure_tag,
                DailyReportProgress.created_at < row.created_at,
            )
            .order_by(DailyReportProgress.created_at.desc(), DailyReportProgress.id.desc())
            .first()
        )
        row._previous_progress = (
            float(previous.progress_percent)
            if previous and previous.progress_percent is not None
            else None
        )

    try:
        wb = export_progress_traceability_workbook(rows)
    except RuntimeError as exc:
        abort(503, description=str(exc))
    return xlsx_response(workbook_to_bytes(wb), "progress_traceability.xlsx")


@bp.route("/project/<int:project_id>/template.xlsx")
def template_xlsx(project_id: int):
    project = get_project_or_403(project_id)
    if not can_submit_for_project(project):
        abort(403)
    try:
        wb = build_template_workbook(project, _all_contract_items(project))
    except RuntimeError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("daily_reports.project_list", project_id=project_id))
    return xlsx_response(
        workbook_to_bytes(wb),
        f"daily_report_template_{project.project_code}.xlsx",
    )


@bp.route("/project/<int:project_id>/export.xlsx")
def export_xlsx(project_id: int):
    project = get_project_or_403(project_id)
    reports = (
        DailyReport.query.filter_by(project_id=project.id)
        .order_by(DailyReport.report_date.desc())
        .limit(200)
        .all()
    )
    try:
        wb = export_reports_workbook(project, reports)
    except RuntimeError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("daily_reports.project_list", project_id=project_id))
    return xlsx_response(
        workbook_to_bytes(wb),
        f"daily_reports_{project.project_code}.xlsx",
    )


@bp.route("/project/<int:project_id>/import", methods=["POST"])
def import_xlsx(project_id: int):
    project = get_project_or_403(project_id)
    if not can_submit_for_project(project):
        flash("شما مجوز ورود گزارش برای این پروژه را ندارید.", "danger")
        return redirect(url_for("daily_reports.project_list", project_id=project_id))

    form = ImportExcelForm()
    if not form.validate_on_submit():
        flash("فایل اکسل معتبر انتخاب نشده است.", "danger")
        return redirect(url_for("daily_reports.project_list", project_id=project_id))

    try:
        result = import_daily_reports_from_workbook(
            project=project,
            file_storage=form.file.data,
            user_id=current_user.id,
            submit_after=bool(form.submit_after.data),
        )
        parts = [
            f"ایجاد: {result['created']}",
            f"به‌روزرسانی: {result['updated']}",
        ]
        if result["untouched"]:
            parts.append(f"بدون تغییر: {result['untouched']}")
        if result["skipped"]:
            parts.append(f"ردیف نامعتبر: {result['skipped']}")
        flash("ورود اکسل انجام شد — " + " | ".join(parts), "success")
        for err in result.get("errors") or []:
            flash(err, "warning")
        if form.submit_after.data and (result["created"] or result["updated"]):
            latest = (
                DailyReport.query.filter_by(project_id=project.id, submitted_by_id=current_user.id)
                .order_by(DailyReport.id.desc())
                .first()
            )
            if latest and latest.status == "submitted":
                notify_daily_report_submitted(latest)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Daily report excel import db error")
        flash("خطای پایگاه داده هنگام ورود اکسل.", "danger")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Daily report excel import failed")
        flash("فایل اکسل خوانده نشد. از قالب استاندارد استفاده کنید.", "danger")
    return redirect(url_for("daily_reports.project_list", project_id=project_id))
