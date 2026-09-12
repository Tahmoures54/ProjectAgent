# Path: pms_app/blueprints/users/routes.py
from __future__ import annotations

import secrets

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from pms_app.extensions import db
from pms_app.models.role import Role
from pms_app.models.user import User
from pms_app.models.plan import Plan  # اضافه شد
from pms_app.utils.entitlements import can_add_user
from pms_app.utils.security import ensure_rbac_seed, is_owner

from . import bp
from .forms import DeleteForm, InviteForm, UserForm

# نقش‌های قابل اختصاص به کاربران عادی (شرکت)
TENANT_ASSIGNABLE_ROLE_NAMES = {"company_admin", "company_user", "manager", "viewer", "contractor"}


# ----------------- Helpers -----------------
def _current_company_id() -> int | None:
    cid = getattr(current_user, "company_id", None)
    try:
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None


def _role_names(user: User) -> set[str]:
    return {r.name.lower() for r in (user.roles or []) if r and r.name}


def _can_manage_users(user: User) -> bool:
    return is_owner(user) or "company_admin" in _role_names(user)


def _enforce_blueprint_access() -> None:
    if not _can_manage_users(current_user):
        abort(403)
    if not is_owner(current_user) and _current_company_id() is None:
        abort(403)


def _enforce_same_company_or_owner(target: User) -> None:
    _enforce_blueprint_access()
    if is_owner(current_user):
        return
    cid = _current_company_id()
    if cid is None or target.company_id != cid:
        abort(404)


def _role_choices_for_current_user() -> list[tuple[int, str]]:
    query = Role.query.order_by(Role.title.asc())
    if not is_owner(current_user):
        query = query.filter(func.lower(Role.name).in_([n.lower() for n in TENANT_ASSIGNABLE_ROLE_NAMES]))
    roles = [(r.id, r.title) for r in query.all()]
    return roles


def _roles_by_ids(selected_ids: list[int]) -> list[Role]:
    ids = {int(x) for x in (selected_ids or [])}
    if not ids:
        return []
    query = Role.query.filter(Role.id.in_(ids))
    if not is_owner(current_user):
        query = query.filter(func.lower(Role.name).in_([n.lower() for n in TENANT_ASSIGNABLE_ROLE_NAMES]))
    return query.all()


def _default_roles_if_none() -> list[Role]:
    r = Role.query.filter(func.lower(Role.name) == "company_user").first()
    return [r] if r else []


def _safe_email(raw: str | None) -> str:
    return (raw or "").strip().lower()


def _redirect_after_users_action():
    """بر اساس نقش، redirect بعد از ایجاد/ویرایش/حذف کاربر"""
    if is_owner(current_user):
        return redirect(url_for("users.owner_dashboard"))
    return redirect(url_for("users.users"))


# ----------------- Blueprint Guard -----------------
@bp.before_request
@login_required
def _users_guard():
    ensure_rbac_seed(update_existing=True)
    _enforce_blueprint_access()


# ----------------- Routes -----------------
@bp.route("/users")
def users():
    # اگر مالک است، به داشبورد مالک هدایت شود
    if is_owner(current_user):
        return redirect(url_for("users.owner_dashboard"))

    query = User.query.filter(User.company_id == _current_company_id())

    pagination = query.order_by(User.id.desc()).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=current_app.config.get("PER_PAGE", 20),
        error_out=False,
    )

    return render_template(
        "users/users.html",
        users=pagination.items,
        pagination=pagination,
        delete_form=DeleteForm(),
        title="مدیریت کاربران",
    )


@bp.route("/owner-dashboard")
@login_required
def owner_dashboard():
    if not is_owner(current_user):
        abort(403)

    # دریافت همه کاربران
    users = User.query.order_by(User.id.desc()).all()

    # دریافت همه پلن‌ها
    plans = Plan.query.order_by(Plan.id.asc()).all()

    return render_template(
        "users/owner_dashboard.html",
        title="داشبورد مالک",
        users=users,
        plans=plans
    )


@bp.route("/users/new", methods=["GET", "POST"])
def user_new():
    form = UserForm()
    form.roles.choices = _role_choices_for_current_user()

    if form.validate_on_submit():
        ok, msg, upgrade_url = can_add_user(current_user.id)
        if not ok:
            flash(msg or "محدودیت پلن اجازه افزودن کاربر را نمی‌دهد.", "warning")
            if upgrade_url:
                return redirect(upgrade_url)
            return _redirect_after_users_action()

        email = _safe_email(form.email.data)
        if User.query.filter(func.lower(User.email) == email).first():
            flash("این ایمیل قابل ثبت نیست.", "danger")
            return render_template("users/user_form.html", form=form, title="کاربر جدید")

        user = User(
            email=email,
            full_name=form.full_name.data or None,
            phone=form.phone.data or None,
            is_active=form.is_active.data,
            company_id=_current_company_id(),
        )

        password = form.password.data or secrets.token_urlsafe(10)
        user.set_password(password)

        selected_roles = _roles_by_ids(form.roles.data) or _default_roles_if_none()
        user.roles = selected_roles

        if any(r.name.lower() == "contractor" for r in (selected_roles or [])):
            user.contractor_company = (form.contractor_company.data or None)

        db.session.add(user)
        try:
            db.session.commit()
            flash("کاربر ایجاد شد.", "success")
            return _redirect_after_users_action()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("خطا در ایجاد کاربر جدید")
            flash("خطای پایگاه داده هنگام ایجاد کاربر.", "danger")
            return render_template("users/user_form.html", form=form, title="کاربر جدید")

    return render_template("users/user_form.html", form=form, title="کاربر جدید")


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def user_edit(user_id):
    user = User.query.get_or_404(user_id)
    _enforce_same_company_or_owner(user)

    form = UserForm(obj=user)
    form.roles.choices = _role_choices_for_current_user()

    if form.validate_on_submit():
        email = _safe_email(form.email.data)
        user.email = email
        user.full_name = form.full_name.data or None
        user.phone = form.phone.data or None
        user.is_active = form.is_active.data

        if form.password.data:
            user.set_password(form.password.data)

        selected_roles = _roles_by_ids(form.roles.data) or _default_roles_if_none()
        user.roles = selected_roles

        if any(r.name.lower() == "contractor" for r in (selected_roles or [])):
            user.contractor_company = (form.contractor_company.data or None)
        else:
            user.contractor_company = None

        try:
            db.session.commit()
            flash("کاربر ویرایش شد.", "success")
            return _redirect_after_users_action()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("خطا در ویرایش کاربر")
            flash("خطای پایگاه داده هنگام ویرایش کاربر.", "danger")

    return render_template("users/user_form.html", form=form, title="ویرایش کاربر", user=user)


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
def user_delete(user_id):
    user = User.query.get_or_404(user_id)
    _enforce_same_company_or_owner(user)

    if user.id == current_user.id:
        flash("شما نمی‌توانید خودتان را حذف کنید.", "warning")
        return _redirect_after_users_action()

    try:
        db.session.delete(user)
        db.session.commit()
        flash("کاربر حذف شد.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("خطا در حذف کاربر")
        flash("خطای پایگاه داده هنگام حذف کاربر.", "danger")

    return _redirect_after_users_action()


@bp.route("/invite", methods=["GET", "POST"])
def invite():
    form = InviteForm()

    if form.validate_on_submit():
        ok, msg, upgrade_url = can_add_user(current_user.id)
        if not ok:
            flash(msg or "محدودیت پلن اجازه دعوت کاربر را نمی‌دهد.", "warning")
            if upgrade_url:
                return redirect(upgrade_url)
            return _redirect_after_users_action()

        email = _safe_email(form.email.data)
        if User.query.filter(func.lower(User.email) == email).first():
            flash("این ایمیل قابل دعوت نیست.", "warning")
            return render_template("users/invite.html", form=form)

        user = User(email=email, is_active=False, company_id=_current_company_id())
        user.roles = _default_roles_if_none()

        db.session.add(user)
        try:
            db.session.commit()
            flash("دعوت‌نامه ذخیره شد و ارسال خواهد شد.", "success")
            return _redirect_after_users_action()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("خطا در ثبت دعوت‌نامه")
            flash("خطا هنگام ذخیره دعوت‌نامه.", "danger")

    return render_template("users/invite.html", form=form, title="دعوت کاربر")