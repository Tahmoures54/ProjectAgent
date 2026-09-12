# Path: pms_app/blueprints/concerns/routes.py
from __future__ import annotations

from typing import List, Optional, Tuple

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from pms_app.extensions import db
from pms_app.models.concern import Concern, ConcernComment, ConcernHistory
from pms_app.models.project import Project
from pms_app.models.project_membership import ProjectMembership
from pms_app.models.user import User
from pms_app.utils.inbox import visible_concerns_query
from pms_app.utils.notify import (
    notify_concern_assigned,
    notify_concern_created,
    notify_concern_escalated,
    notify_concern_status,
)
from pms_app.utils.security import ensure_rbac_seed

from . import bp
from .forms import ConcernCommentForm, ConcernForm, ConcernStatusForm


def _company_id() -> Optional[int]:
    cid = getattr(current_user, "company_id", None)
    try:
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None


def _accessible_projects() -> List[Project]:
    if current_user.is_owner:
        return Project.query.filter_by(status="active").order_by(Project.project_name).limit(200).all()
    cid = _company_id()
    if not cid:
        return []
    q = Project.query.filter_by(company_id=cid, status="active")
    if not current_user.is_company_admin:
        q = (
            q.join(ProjectMembership)
            .filter(ProjectMembership.user_id == current_user.id)
            .filter(ProjectMembership.status == "active")
        )
    return q.order_by(Project.project_name).limit(100).all()


def _assignee_choices(project_id: Optional[int] = None) -> List[Tuple[int, str]]:
    choices = [(0, "— بدون مسئول —")]
    cid = _company_id()
    if not cid and not current_user.is_owner:
        return choices
    q = User.query.filter_by(is_active=True)
    if cid:
        q = q.filter(User.company_id == cid)
    if project_id:
        q = (
            q.join(ProjectMembership, ProjectMembership.user_id == User.id)
            .filter(ProjectMembership.project_id == project_id)
            .filter(ProjectMembership.status == "active")
        )
    for u in q.order_by(User.full_name).limit(80).all():
        choices.append((u.id, u.full_name or u.email))
    return choices


def _assignee_in_company(user_id: Optional[int], company_id: Optional[int]) -> Optional[int]:
    if not user_id:
        return None
    target = db.session.get(User, int(user_id))
    if not target:
        return None
    if company_id is not None and int(target.company_id or 0) != int(company_id):
        return None
    return int(target.id)


def get_concern_or_403(concern_id: int) -> Concern:
    concern = db.session.get(Concern, concern_id)
    if not concern:
        abort(404)
    if not concern.can_view(current_user):
        abort(403)
    return concern


@bp.before_request
@login_required
def _guard():
    ensure_rbac_seed(update_existing=True)
    if not getattr(current_user, "is_active", True):
        flash("حساب شما غیرفعال است.", "danger")
        return redirect(url_for("main.dashboard"))


@bp.route("/")
def index():
    status = request.args.get("status", "").strip()
    priority = request.args.get("priority", "").strip()
    category = request.args.get("category", "").strip()
    visibility = request.args.get("visibility", "").strip()
    project_id = request.args.get("project_id", type=int)
    q = request.args.get("q", "").strip()
    mine = request.args.get("mine", "").strip() == "1"

    query = visible_concerns_query(current_user)

    if status:
        query = query.filter(Concern.status == status)
    if priority:
        query = query.filter(Concern.priority == priority)
    if category:
        query = query.filter(Concern.category == category)
    if visibility:
        query = query.filter(Concern.visibility == visibility)
    if project_id:
        query = query.filter(Concern.project_id == project_id)
    if mine:
        query = query.filter(
            or_(Concern.raised_by_id == current_user.id, Concern.assignee_id == current_user.id)
        )
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Concern.title.ilike(like), Concern.description.ilike(like)))

    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("PER_PAGE", 20)
    pagination = query.order_by(
        Concern.priority.desc(),
        Concern.updated_at.desc(),
    ).paginate(page=page, per_page=per_page, error_out=False)

    projects = _accessible_projects()
    return render_template(
        "concerns/list.html",
        concerns=pagination.items,
        pagination=pagination,
        projects=projects,
        status=status,
        priority=priority,
        category=category,
        visibility=visibility,
        project_id=project_id,
        q=q,
        mine=mine,
        status_labels=Concern.STATUS_LABELS,
        priority_labels=Concern.PRIORITY_LABELS,
        category_labels=Concern.CATEGORY_LABELS,
        visibility_labels=Concern.VISIBILITY_LABELS,
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    form = ConcernForm()
    projects = _accessible_projects()
    form.project_id.choices = [(0, "— سطح شرکت (بدون پروژه) —")] + [
        (p.id, f"{p.project_code} — {p.project_name}") for p in projects
    ]
    form.assignee_id.choices = _assignee_choices()

    if request.method == "GET":
        pid = request.args.get("project_id", type=int)
        if pid:
            form.project_id.data = pid
            form.assignee_id.choices = _assignee_choices(pid)

    if form.validate_on_submit():
        cid = _company_id()
        if not cid and not current_user.is_owner:
            flash("کاربر به شرکتی متصل نیست.", "danger")
            return redirect(url_for("concerns.index"))

        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        if project_id:
            project = db.session.get(Project, project_id)
            if not project or not current_user.can_access_project(project):
                flash("دسترسی به این پروژه ندارید.", "danger")
                return redirect(url_for("concerns.index"))
            cid = project.company_id

        tags = []
        if form.tags_raw.data:
            tags = [t.strip() for t in form.tags_raw.data.split(",") if t.strip()][:15]

        assignee_id = form.assignee_id.data or None
        if assignee_id == 0:
            assignee_id = None
        assignee_id = _assignee_in_company(assignee_id, cid)

        visibility = form.visibility.data or "project"
        if visibility == "project" and not project_id:
            visibility = "company"

        concern = Concern(
            company_id=cid,
            project_id=project_id,
            title=form.title.data.strip(),
            description=form.description.data or None,
            category=form.category.data,
            priority=form.priority.data,
            visibility=visibility,
            raised_by_id=current_user.id,
            assignee_id=assignee_id,
            due_date=form.due_date.data,
            tags=tags or None,
            status="open",
        )
        db.session.add(concern)
        try:
            db.session.flush()
            concern.add_history(
                user_id=current_user.id,
                action="create",
                from_status=None,
                to_status="open",
                note="ثبت کانسرن جدید",
            )
            db.session.commit()
            notify_concern_created(concern)
            if assignee_id:
                notify_concern_assigned(concern)
            flash("کانسرن با موفقیت ثبت شد.", "success")
            return redirect(url_for("concerns.detail", concern_id=concern.id))
        except SQLAlchemyError:
            db.session.rollback()
            flash("خطای پایگاه داده هنگام ثبت کانسرن.", "danger")

    return render_template(
        "concerns/form.html",
        form=form,
        title="ثبت کانسرن جدید",
        concern=None,
    )


@bp.route("/<int:concern_id>")
def detail(concern_id: int):
    concern = get_concern_or_403(concern_id)
    comments = concern.comments.order_by(ConcernComment.created_at.asc()).all()
    is_manager_like = (
        current_user.is_owner
        or current_user.is_company_admin
        or current_user.has_permission("concerns.manage")
        or current_user.has_role("manager")
    )
    if not is_manager_like:
        comments = [c for c in comments if not c.is_internal]

    history = concern.history.order_by(ConcernHistory.created_at.asc()).all()
    comment_form = ConcernCommentForm()
    status_form = ConcernStatusForm() if concern.can_edit(current_user) else None
    if status_form:
        status_form.assignee_id.choices = _assignee_choices(concern.project_id)

    return render_template(
        "concerns/detail.html",
        concern=concern,
        comments=comments,
        history=history,
        comment_form=comment_form,
        status_form=status_form,
        can_edit=concern.can_edit(current_user),
        status_labels=Concern.STATUS_LABELS,
        priority_labels=Concern.PRIORITY_LABELS,
        category_labels=Concern.CATEGORY_LABELS,
        visibility_labels=Concern.VISIBILITY_LABELS,
    )


@bp.route("/<int:concern_id>/edit", methods=["GET", "POST"])
def edit(concern_id: int):
    concern = get_concern_or_403(concern_id)
    if not concern.can_edit(current_user):
        flash("مجوز ویرایش این کانسرن را ندارید.", "danger")
        return redirect(url_for("concerns.detail", concern_id=concern_id))

    form = ConcernForm(obj=concern)
    projects = _accessible_projects()
    form.project_id.choices = [(0, "— سطح شرکت (بدون پروژه) —")] + [
        (p.id, f"{p.project_code} — {p.project_name}") for p in projects
    ]
    form.assignee_id.choices = _assignee_choices(concern.project_id)

    if request.method == "GET":
        form.project_id.data = concern.project_id or 0
        form.assignee_id.data = concern.assignee_id or 0
        form.tags_raw.data = ", ".join(concern.tags or [])

    if form.validate_on_submit():
        project_id = form.project_id.data or None
        if project_id == 0:
            project_id = None
        old_assignee = concern.assignee_id
        assignee_id = form.assignee_id.data or None
        if assignee_id == 0:
            assignee_id = None
        assignee_id = _assignee_in_company(assignee_id, concern.company_id)

        if project_id:
            project = db.session.get(Project, project_id)
            if not project or not current_user.can_access_project(project):
                flash("دسترسی به این پروژه ندارید.", "danger")
                return redirect(url_for("concerns.detail", concern_id=concern_id))
            if int(project.company_id) != int(concern.company_id):
                flash("پروژه باید متعلق به همان شرکت باشد.", "danger")
                return redirect(url_for("concerns.detail", concern_id=concern_id))

        tags = []
        if form.tags_raw.data:
            tags = [t.strip() for t in form.tags_raw.data.split(",") if t.strip()][:15]

        visibility = form.visibility.data or "project"
        if visibility == "project" and not project_id:
            visibility = "company"

        concern.title = form.title.data.strip()
        concern.description = form.description.data or None
        concern.project_id = project_id
        concern.category = form.category.data
        concern.priority = form.priority.data
        concern.visibility = visibility
        concern.assignee_id = assignee_id
        concern.due_date = form.due_date.data
        concern.tags = tags or None

        try:
            concern.add_history(
                user_id=current_user.id,
                action="update",
                from_status=concern.status,
                to_status=concern.status,
                note="ویرایش کانسرن",
            )
            db.session.commit()
            if assignee_id and assignee_id != old_assignee:
                notify_concern_assigned(concern)
            flash("کانسرن به‌روز شد.", "success")
            return redirect(url_for("concerns.detail", concern_id=concern.id))
        except SQLAlchemyError:
            db.session.rollback()
            flash("خطای پایگاه داده.", "danger")

    return render_template(
        "concerns/form.html",
        form=form,
        title="ویرایش کانسرن",
        concern=concern,
    )


@bp.route("/<int:concern_id>/comment", methods=["POST"])
def add_comment(concern_id: int):
    concern = get_concern_or_403(concern_id)
    form = ConcernCommentForm()
    if not form.validate_on_submit():
        flash("متن نظر نامعتبر است.", "danger")
        return redirect(url_for("concerns.detail", concern_id=concern_id))

    is_internal = bool(form.is_internal.data)
    if is_internal and not (
        current_user.is_owner
        or current_user.is_company_admin
        or current_user.has_permission("concerns.manage")
        or current_user.has_role("manager")
    ):
        is_internal = False

    comment = ConcernComment(
        concern_id=concern.id,
        user_id=current_user.id,
        body=form.body.data.strip(),
        is_internal=is_internal,
    )
    db.session.add(comment)
    concern.add_history(
        user_id=current_user.id,
        action="comment",
        from_status=concern.status,
        to_status=concern.status,
        note="افزودن نظر" + (" (داخلی)" if is_internal else ""),
    )
    try:
        db.session.commit()
        flash("نظر ثبت شد.", "success")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطا در ثبت نظر.", "danger")
    return redirect(url_for("concerns.detail", concern_id=concern_id))


@bp.route("/<int:concern_id>/status", methods=["POST"])
def change_status(concern_id: int):
    concern = get_concern_or_403(concern_id)
    if not concern.can_edit(current_user):
        flash("مجوز تغییر وضعیت ندارید.", "danger")
        return redirect(url_for("concerns.detail", concern_id=concern_id))

    form = ConcernStatusForm()
    form.assignee_id.choices = _assignee_choices(concern.project_id)
    if not form.validate_on_submit():
        flash("فرم نامعتبر است.", "danger")
        return redirect(url_for("concerns.detail", concern_id=concern_id))

    action = form.action.data
    note = (form.note.data or "").strip() or None
    new_assignee = form.assignee_id.data or None
    if new_assignee == 0:
        new_assignee = None
    new_assignee = _assignee_in_company(new_assignee, concern.company_id)

    try:
        assigned_changed = False
        if new_assignee is not None and new_assignee != concern.assignee_id:
            concern.assignee_id = new_assignee
            concern.add_history(
                user_id=current_user.id,
                action="assign",
                from_status=concern.status,
                to_status=concern.status,
                note=f"تغییر مسئول به #{new_assignee}",
            )
            assigned_changed = True

        if action == "acknowledge":
            concern.acknowledge(current_user.id)
        elif action == "start_progress":
            concern.start_progress(current_user.id)
        elif action == "resolve":
            concern.resolve(current_user.id, resolution=note)
        elif action == "close":
            concern.close(current_user.id, note=note)
        elif action == "escalate":
            concern.escalate(current_user.id, note=note)
        elif action == "reopen":
            concern.reopen(current_user.id, note=note)
        else:
            flash("عملیات نامعتبر.", "danger")
            return redirect(url_for("concerns.detail", concern_id=concern_id))

        db.session.commit()

        if assigned_changed:
            notify_concern_assigned(concern)
        if action == "escalate":
            notify_concern_escalated(concern)
        if action in ("resolve", "close", "reopen"):
            notify_concern_status(concern, action=action)

        flash("وضعیت کانسرن به‌روز شد.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطای پایگاه داده.", "danger")

    return redirect(url_for("concerns.detail", concern_id=concern_id))


@bp.route("/<int:concern_id>/delete", methods=["POST"])
def delete(concern_id: int):
    concern = get_concern_or_403(concern_id)
    if not (
        current_user.is_owner
        or current_user.is_company_admin
        or (concern.raised_by_id == current_user.id and concern.status == "open")
    ):
        flash("مجوز حذف ندارید.", "danger")
        return redirect(url_for("concerns.detail", concern_id=concern_id))
    try:
        db.session.delete(concern)
        db.session.commit()
        flash("کانسرن حذف شد.", "info")
    except SQLAlchemyError:
        db.session.rollback()
        flash("خطا در حذف.", "danger")
    return redirect(url_for("concerns.index"))
