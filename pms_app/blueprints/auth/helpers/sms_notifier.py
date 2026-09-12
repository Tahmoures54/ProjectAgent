# Path: pms_app/blueprints/auth/helpers/sms_notifier.py
from __future__ import annotations

from datetime import datetime

from flask import current_app, url_for

from pms_app.models.user import User
from pms_app.utils.sms import send_sms

from .security import get_client_ip

try:
    from pms_app.models.sms_log import SmsLog  # type: ignore
except Exception:
    SmsLog = None  # type: ignore


def _recently_sent(phone: str, purpose: str, within_seconds: int) -> bool:
    if SmsLog is None:
        return False
    try:
        since = datetime.utcfromtimestamp(datetime.utcnow().timestamp() - within_seconds)
        q = SmsLog.query
        if hasattr(SmsLog, "to"):
            q = q.filter(SmsLog.to == phone)
        if hasattr(SmsLog, "purpose"):
            q = q.filter(SmsLog.purpose == purpose)
        if hasattr(SmsLog, "created_at"):
            q = q.filter(SmsLog.created_at >= since)
        return q.first() is not None
    except Exception:
        return False


def _user_allows_sms(user: User, *, transactional: bool) -> bool:
    if not (getattr(user, "phone", None) or "").strip():
        return False

    if not transactional and hasattr(user, "sms_opt_in"):
        if not bool(getattr(user, "sms_opt_in", False)):
            return False

    if hasattr(user, "phone_verified"):
        if bool(getattr(user, "phone_verified", False)):
            return True
        cfg_key = "SMS_ALLOW_UNVERIFIED_TRANSACTIONAL" if transactional else "SMS_ALLOW_UNVERIFIED_WELCOME"
        return bool(current_app.config.get(cfg_key, True))

    return True


def _send(user: User, phone: str, purpose: str, msg: str, within: int) -> None:
    if _recently_sent(phone, purpose, within_seconds=within):
        return
    send_sms(to=phone, message=msg, purpose=purpose, user_id=int(user.id))


def send_welcome_signup(user: User) -> None:
    if not bool(current_app.config.get("SMS_WELCOME_SIGNUP_ENABLED", True)):
        return
    if not _user_allows_sms(user, transactional=False):
        return

    phone = (user.phone or "").strip()
    if not phone:
        return

    app_name = current_app.config.get("APP_NAME", "Project Agent")
    name = (getattr(user, "full_name", "") or "").strip() or "کاربر عزیز"
    login_url = url_for("auth.login", _external=True)
    msg = f"{app_name}\nخوش آمدید {name}!\nثبت‌نام شما با موفقیت انجام شد.\nورود: {login_url}"
    _send(user, phone, "WELCOME_SIGNUP", msg, within=24 * 3600)


def send_login_notification(user: User, *, first_login: bool, new_device: bool) -> None:
    phone = (getattr(user, "phone", None) or "").strip()
    if not phone:
        return

    app_name = current_app.config.get("APP_NAME", "Project Agent")

    if first_login and bool(current_app.config.get("SMS_WELCOME_FIRST_LOGIN_ENABLED", True)):
        if not _user_allows_sms(user, transactional=False):
            return
        name = (getattr(user, "full_name", "") or "").strip()
        prefix = f"{name}، " if name else ""
        dashboard_url = url_for("main.dashboard", _external=True)
        msg = f"{app_name}\n{prefix}اولین ورود شما با موفقیت انجام شد.\nشروع کار: {dashboard_url}"
        _send(user, phone, "WELCOME_FIRST_LOGIN", msg, within=24 * 3600)
        return

    if new_device and bool(current_app.config.get("SMS_LOGIN_ALERT_ENABLED", True)):
        if not _user_allows_sms(user, transactional=True):
            return
        now_str = datetime.utcnow().strftime("%Y/%m/%d %H:%M")
        ip = get_client_ip() or "-"
        msg = (
            f"{app_name}\nورود موفق به حساب شما انجام شد.\n"
            f"زمان: {now_str}\nIP: {ip}\nاگر شما نبودید، رمز را تغییر دهید."
        )
        _send(user, phone, "LOGIN_ALERT_NEW_DEVICE", msg, within=10 * 60)


def send_forgot_password(user: User, reset_link: str) -> None:
    if not bool(current_app.config.get("SMS_FORGOT_PASSWORD_ENABLED", True)):
        return
    if not _user_allows_sms(user, transactional=True):
        return

    phone = (user.phone or "").strip()
    if not phone:
        return

    app_name = current_app.config.get("APP_NAME", "Project Agent")
    msg = f"{app_name}\nلینک بازیابی رمز عبور:\n{reset_link}\nاگر شما درخواست نداده‌اید، نادیده بگیرید."
    _send(user, phone, "PASSWORD_RESET", msg, within=60)