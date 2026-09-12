# Path: pms_app/blueprints/auth/routes.py
from __future__ import annotations

from datetime import datetime

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pms_app.extensions import db
from pms_app.models.role import Role
from pms_app.models.user import User
from pms_app.utils.security import configured_owner_emails, ensure_rbac_seed, is_owner as is_owner_user

from . import bp
from .forms import ChangePasswordForm, ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm
from .helpers import sms_notifier, subscription
from .helpers.captcha import clear_captcha, ensure_captcha, verify_captcha
from .helpers.security import (
    get_client_ip,
    get_user_agent,
    is_safe_redirect_url,
    normalize_digits,
    normalize_otp,
)
from .helpers.tokens import generate_reset_token, send_reset_link, verify_reset_token
from .helpers.two_factor import (
    build_provisioning_uri,
    generate_totp_secret,
    make_qr_data_uri,
    verify_totp,
)

try:
    from pms_app.models.company import Company  # type: ignore
except Exception:
    Company = None  # type: ignore

try:
    from .forms import OTPForm  # type: ignore
except Exception:
    from flask_wtf import FlaskForm
    from wtforms import StringField, SubmitField
    from wtforms.validators import DataRequired, Length

    class OTPForm(FlaskForm):
        otp_code = StringField("کد ۶ رقمی", validators=[DataRequired(), Length(min=6, max=6)])
        submit = SubmitField("تأیید")


# =========================================================
# Shared login logic
# =========================================================
def _detect_login_context(user: User) -> tuple[bool, bool]:
    """Return (first_login, new_device)."""
    old_last = getattr(user, "last_login_at", None)
    old_ip = getattr(user, "last_login_ip", None)
    old_ua = getattr(user, "last_login_user_agent", None)

    new_ip = get_client_ip()
    new_ua = get_user_agent()

    first_login = old_last is None
    new_device = False
    try:
        if (old_ip and new_ip and old_ip != new_ip) or (old_ua and new_ua and old_ua != new_ua):
            new_device = True
        if not first_login and old_ip is None and old_ua is None and (new_ip or new_ua):
            new_device = True
    except Exception:
        new_device = False

    return first_login, new_device


def _update_login_metadata(user: User) -> None:
    user.last_login_at = datetime.utcnow()
    if hasattr(user, "last_login_ip"):
        user.last_login_ip = get_client_ip()
    if hasattr(user, "last_login_user_agent"):
        user.last_login_user_agent = get_user_agent()
    db.session.commit()


def _is_platform_owner(user: User) -> bool:
    raw = current_app.config.get("OWNER_EMAILS") or current_app.config.get("OWNER_EMAIL") or ""
    owner_list = [e.strip().lower() for e in raw.split(",") if e.strip()]
    try:
        return is_owner_user(user) or ((user.email or "").strip().lower() in owner_list)
    except Exception:
        return (user.email or "").strip().lower() in owner_list


def _post_login_redirect(user: User, next_url: str | None):
    """Owner → users page. Others → paywall/dashboard/next."""
    if _is_platform_owner(user):
        if next_url and is_safe_redirect_url(next_url):
            return redirect(next_url)
        return redirect(url_for("users.users"))

    resp = subscription.enforce_paywall(user)
    if resp is not None:
        return resp

    if next_url and is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for("main.dashboard"))


def _finalize_login(user: User, *, remember: bool, next_url: str | None):
    first_login, new_device = _detect_login_context(user)
    _update_login_metadata(user)
    login_user(user, remember=remember)

    try:
        sms_notifier.send_login_notification(user, first_login=first_login, new_device=new_device)
    except Exception:
        current_app.logger.exception("Failed sending login SMS")

    flash("ورود موفقیت‌آمیز بود.", "success")
    return _post_login_redirect(user, next_url)


# =========================================================
# Routes
# =========================================================
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = (form.email.data or "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first() if email else None

        if user and user.is_active and user.check_password(form.password.data):
            # 2FA?
            if getattr(user, "two_fa_enabled", False) and getattr(user, "two_fa_secret", None):
                session["pre_2fa_user_id"] = int(user.id)
                session["pre_2fa_remember"] = bool(form.remember.data)
                next_url = request.args.get("next")
                if next_url and is_safe_redirect_url(next_url):
                    session["pre_2fa_next"] = next_url
                else:
                    session.pop("pre_2fa_next", None)
                flash("کد ۲ مرحله‌ای را وارد کنید.", "info")
                return redirect(url_for("auth.login_2fa"))

            return _finalize_login(user, remember=bool(form.remember.data), next_url=request.args.get("next"))

        flash("ایمیل یا رمز عبور اشتباه است.", "danger")

    return render_template("auth/login.html", form=form)


@bp.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    user_id = session.get("pre_2fa_user_id")
    if not user_id:
        flash("جلسه ورود منقضی شده است. دوباره وارد شوید.", "warning")
        return redirect(url_for("auth.login"))

    user = db.session.get(User, int(user_id))
    if not user or not user.is_active or not user.two_fa_enabled or not user.two_fa_secret:
        for key in ("pre_2fa_user_id", "pre_2fa_remember", "pre_2fa_next"):
            session.pop(key, None)
        flash("ورود دو مرحله‌ای برای این حساب فعال نیست.", "warning")
        return redirect(url_for("auth.login"))

    form = OTPForm()
    if form.validate_on_submit():
        code = normalize_otp(form.otp_code.data)
        if verify_totp(user.two_fa_secret, code):
            remember = bool(session.get("pre_2fa_remember"))
            next_url = session.get("pre_2fa_next")
            for key in ("pre_2fa_user_id", "pre_2fa_remember", "pre_2fa_next"):
                session.pop(key, None)
            return _finalize_login(user, remember=remember, next_url=next_url)

        flash("کد ۲ مرحله‌ای نادرست است.", "danger")

    return render_template("auth/verify_2fa.html", form=form)


@bp.route("/enable-2fa", methods=["GET", "POST"])
@login_required
def enable_2fa():
    form = OTPForm()

    if current_user.two_fa_enabled and current_user.two_fa_secret:
        flash("احراز هویت دو مرحله‌ای از قبل فعال است.", "info")

    secret = session.get("2fa_secret") or generate_totp_secret()
    if not secret:
        flash("برای فعال‌سازی 2FA باید pyotp نصب باشد.", "danger")
        return redirect(url_for("main.dashboard"))
    session["2fa_secret"] = secret

    issuer = current_app.config.get("APP_NAME", "Project Agent")
    account = current_user.email or f"user-{current_user.id}"
    uri = build_provisioning_uri(secret, account, issuer)

    try:
        qrcode_url = make_qr_data_uri(uri) if uri else None
    except Exception:
        qrcode_url = None

    if form.validate_on_submit():
        code = normalize_otp(form.otp_code.data)
        if not verify_totp(secret, code):
            flash("کد وارد شده صحیح نیست.", "danger")
            return render_template("auth/enable_2fa.html", form=form, qrcode_url=qrcode_url)

        current_user.two_fa_secret = secret
        current_user.two_fa_enabled = True
        db.session.commit()
        session.pop("2fa_secret", None)
        flash("احراز هویت دو مرحله‌ای با موفقیت فعال شد.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/enable_2fa.html", form=form, qrcode_url=qrcode_url)


@bp.route("/disable-2fa", methods=["POST"])
@login_required
def disable_2fa():
    current_user.two_fa_enabled = False
    current_user.two_fa_secret = None
    db.session.commit()
    flash("احراز هویت دو مرحله‌ای غیرفعال شد.", "info")
    return redirect(url_for("main.dashboard"))


@bp.route("/logout")
def logout():
    for key in ("pre_2fa_user_id", "pre_2fa_remember", "pre_2fa_next", "2fa_secret"):
        session.pop(key, None)

    if current_user.is_authenticated:
        logout_user()
        flash("با موفقیت خارج شدید.", "info")
    return redirect(url_for("main.home"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    ensure_rbac_seed(update_existing=True)

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    is_first_user = int(db.session.scalar(select(func.count(User.id))) or 0) == 0
    ensure_captcha(regenerate=(request.method == "GET"))
    form = RegisterForm()

    def _render_form():
        ensure_captcha(regenerate=True)
        return render_template(
            "auth/signup.html",
            form=form,
            is_first_user=is_first_user,
            captcha_a=session.get("captcha_a"),
            captcha_b=session.get("captcha_b"),
        )

    if form.validate_on_submit():
        # Terms
        if request.form.get("accept_terms") != "on":
            flash("برای ثبت‌نام باید با شرایط خدمات و سیاست حریم خصوصی موافقت کنید.", "warning")
            return _render_form()

        # Captcha
        if not verify_captcha(normalize_digits(request.form.get("captcha_answer", ""))):
            flash("پاسخ کپچا نادرست است. دوباره تلاش کنید.", "danger")
            return _render_form()

        email = (form.email.data or "").strip().lower()
        full_name = (form.full_name.data or "").strip()
        company_name = " ".join((form.company_name.data or "").strip().split())
        phone = (form.phone.data or "").strip() if hasattr(form, "phone") else ""

        if email and User.query.filter(func.lower(User.email) == email).first():
            flash("این ایمیل قبلاً ثبت شده است.", "danger")
            return _render_form()

        # Create user
        user = _build_user(email, full_name, phone, company_name, form.password.data)
        company = _assign_roles_and_company(user, email, company_name)

        db.session.add(user)

        try:
            db.session.flush()
            if company is not None and hasattr(company, "created_by_user_id"):
                company.created_by_user_id = int(user.id)

            owner_emails = configured_owner_emails()
            if email not in owner_emails:
                if subscription.is_company_based() and company is not None:
                    subscription.get_or_create_for_company(
                        company_id=int(company.id), billing_user_id=int(user.id)
                    )
                else:
                    subscription.get_or_create_for_user_legacy(user)

            db.session.commit()

        except IntegrityError:
            db.session.rollback()
            current_app.logger.exception("IntegrityError during register")
            flash("ثبت‌نام انجام نشد (ایمیل تکراری یا محدودیت دیتابیس).", "danger")
            return _render_form()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Register failed")
            flash("خطای غیرمنتظره هنگام ثبت‌نام رخ داد. دوباره تلاش کنید.", "danger")
            return _render_form()

        clear_captcha()

        try:
            sms_notifier.send_welcome_signup(user)
        except Exception:
            current_app.logger.exception("Failed sending welcome signup SMS")

        flash("ثبت‌نام با موفقیت انجام شد. حالا می‌توانید وارد شوید.", "success")
        return redirect(url_for("auth.login"))

    return render_template(
        "auth/signup.html",
        form=form,
        is_first_user=is_first_user,
        captcha_a=session.get("captcha_a"),
        captcha_b=session.get("captcha_b"),
    )


def _build_user(email: str, full_name: str, phone: str, company_name: str, password: str) -> User:
    user = User()
    user.full_name = full_name
    user.email = email
    user.is_active = True
    if hasattr(user, "company_name"):
        user.company_name = company_name
    if hasattr(user, "phone"):
        user.phone = phone
    user.set_password(password)
    return user


def _get_role(name: str) -> Role | None:
    return Role.query.filter(func.lower(Role.name) == name.strip().lower()).first()


def _assign_roles_and_company(user: User, email: str, company_name: str):
    owner_emails = configured_owner_emails()
    owner_signup = bool(email) and email in owner_emails

    owner_role = _get_role("owner")
    company_admin_role = _get_role("company_admin")
    viewer_role = _get_role("viewer")
    legacy_admin_role = _get_role("admin")

    if owner_signup:
        if owner_role:
            user.roles.append(owner_role)
        return None

    use_company_mode = (Company is not None) and hasattr(user, "company_id")

    if use_company_mode:
        company = Company(name=company_name, is_active=True)
        db.session.add(company)
        db.session.flush()
        user.company_id = int(company.id)

        if company_admin_role:
            user.roles.append(company_admin_role)
        elif viewer_role:
            user.roles.append(viewer_role)
        return company

    # Legacy fallback
    is_first = int(db.session.scalar(select(func.count(User.id))) or 0) == 0
    if is_first and legacy_admin_role:
        user.roles.append(legacy_admin_role)
    elif viewer_role:
        user.roles.append(viewer_role)
    return None


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = (form.email.data or "").strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first() if email else None

        if user and user.is_active:
            token = generate_reset_token(user)
            link = url_for("auth.reset_password", token=token, _external=True)
            send_reset_link(user.email, link)
            try:
                sms_notifier.send_forgot_password(user, link)
            except Exception:
                current_app.logger.exception("Failed sending forgot-password SMS")

        flash("اگر این ایمیل در سیستم ثبت شده باشد، لینک بازیابی ارسال می‌شود.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    max_age = current_app.config.get("RESET_TOKEN_MAX_AGE_SECONDS", 3600)
    user_id = verify_reset_token(token, max_age_seconds=max_age)
    if not user_id:
        flash("لینک بازیابی نامعتبر است یا منقضی شده.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.get(User, int(user_id))
    if not user or not user.is_active:
        flash("کاربر یافت نشد یا غیرفعال است.", "danger")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("رمز عبور با موفقیت تغییر کرد. حالا وارد شوید.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/change_password.html", form=form, token=token)


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("رمز فعلی اشتباه است.", "danger")
            return render_template("auth/change_password.html", form=form)

        current_user.set_password(form.new_password.data)
        db.session.commit()
        flash("رمز عبور با موفقیت تغییر کرد.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/change_password.html", form=form)