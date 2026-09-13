# Path: pms_app/blueprints/daily_reports/routes.py
from __future__ import annotations

import json
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
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from pms_app.extensions import db
from pms_app.models.daily_report import DailyReport, DailyReportHistory
from pms_app.models.item import ContractItem
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
    import_daily_reports_from_workbook,
)
from .forms import DailyReportForm, ImportExcelForm, ReviewForm


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
        elif expected_parts == 4:
            result.append(
                {
                    "contract_item_id": _safe_int(parts[0]),
                    "progress_percent": _safe_float(parts[1] if len(parts) > 1 else None),
                    "quantity_done": _safe_float(parts[2] if len(parts) > 2 else None),
                    "notes": parts[3] if len(parts) > 3 else "",
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
            return rows
    expected = {"manpower": 2, "equipment": 3, "progress": 4, "materials": 4}.get(kind, 2)
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
    if report.manpower_details and not report.manpower_total:
        report.manpower_total = sum(int(x.get("count") or 0) for x in report.manpower_details)


def _hydrate_form(form: DailyReportForm, report: DailyReport) -> None:
    form.manpower_details_raw.data = dumps_rows(report.manpower_details)
    form.equipment_details_raw.data = dumps_rows(report.equipment_details)
    form.progress_updates_raw.data = dumps_rows(report.progress_updates)
    form.materials_received_raw.data = dumps_rows(report.materials_received)


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
    can_approve = report.is_pending_approval and can_manage_project_reports(report.project)
    history = report.history.order_by(DailyReportHistory.created_at.asc()).all()
    review_form = ReviewForm() if can_approve else None
    return render_template(
        "daily_reports/detail.html",
        report=report,
        history=history,
        can_edit=can_edit,
        can_approve=can_approve,
        review_form=review_form,
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
