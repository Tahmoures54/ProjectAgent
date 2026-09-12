# Path: pms_app/utils/security.py
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from flask import abort, current_app, flash
from flask_login import current_user
from sqlalchemy import func

from pms_app.extensions import db

# Config keys for platform owner emails (comma-separated OWNER_EMAILS supported)
OWNER_EMAIL_KEY = "OWNER_EMAIL"
OWNER_EMAILS_KEY = "OWNER_EMAILS"

# Default system roles (RBAC seed)
# permissions are comma-separated strings. Use '*' for full access.
_DEFAULT_ROLES: list[dict] = [
    {
        "name": "owner",
        "title": "مالک سیستم",
        "description": "مالک کامل پلتفرم - دسترسی نامحدود",
        "permissions": "*",
    },
    {
        "name": "admin",
        "title": "ادمین پلتفرم",
        "description": "ادمین سطح سیستم",
        "permissions": "*",
    },
    {
        "name": "company_admin",
        "title": "ادمین شرکت",
        "description": "مدیر کامل شرکت - تمام دسترسی‌های لازم",
        "permissions": (
            "projects.read,projects.create,projects.write,projects.update,projects.delete,"
            "contracts.read,contracts.create,contracts.write,contracts.update,contracts.delete,"
            "items.read,items.create,items.write,items.delete,"
            "reports.read,reports.create,reports.update,reports.delete,"
            "daily_reports.read,daily_reports.create,daily_reports.update,daily_reports.approve,daily_reports.delete,"
            "concerns.read,concerns.create,concerns.update,concerns.manage,concerns.delete,"
            "users.read,users.create,users.update,users.delete,users.manage,"
            "roles.read,roles.manage,"
            "billing.read,billing.manage"
        ),
    },
    {
        "name": "company_user",
        "title": "کاربر شرکت",
        "description": "کاربر عادی شرکت با دسترسی پایه",
        "permissions": (
            "projects.read,items.read,contracts.read,reports.read,"
            "daily_reports.read,daily_reports.create,"
            "concerns.read,concerns.create"
        ),
    },
    {
        "name": "manager",
        "title": "مدیر پروژه/تیم",
        "description": "مدیریت پروژه‌ها + تأیید گزارش روزانه + مدیریت کانسرن",
        "permissions": (
            "projects.read,projects.create,projects.write,projects.update,"
            "contracts.read,contracts.create,contracts.write,"
            "items.read,items.create,items.write,"
            "reports.read,"
            "daily_reports.read,daily_reports.create,daily_reports.update,daily_reports.approve,"
            "concerns.read,concerns.create,concerns.update,concerns.manage"
        ),
    },
    {
        "name": "viewer",
        "title": "مشاهده‌گر",
        "description": "فقط مشاهده",
        "permissions": (
            "projects.read,contracts.read,items.read,reports.read,"
            "daily_reports.read,concerns.read"
        ),
    },
    {
        "name": "contractor",
        "title": "پیمانکار",
        "description": "پیمانکار + گزارش روزانه + ثبت کانسرن",
        "permissions": (
            "projects.read,items.read,items.write,"
            "daily_reports.read,daily_reports.create,daily_reports.update,"
            "concerns.read,concerns.create"
        ),
    },
]


def _normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def configured_owner_emails() -> set[str]:
    """Owner identity comes only from config, never from a hardcoded inbox."""
    emails: set[str] = set()
    try:
        cfg = current_app.config
    except Exception:
        return emails
    for key in (OWNER_EMAIL_KEY, OWNER_EMAILS_KEY):
        raw = cfg.get(key) or ""
        for part in str(raw).split(","):
            email = _normalize_email(part)
            if email:
                emails.add(email)
    return emails


def is_owner(user=None) -> bool:
    """
    Return True if the given user (or current_user) is considered platform owner.
    This checks:
      - user.is_owner property (if present)
      - has_role('owner')
      - email match with OWNER_EMAIL / OWNER_EMAILS config
    """
    if user is None:
        user = current_user
    if not getattr(user, "is_authenticated", False):
        return False

    # direct attribute (model-level)
    if getattr(user, "is_owner", False):
        return True

    # role check
    if hasattr(user, "has_role") and user.has_role("owner"):
        return True

    return _normalize_email(getattr(user, "email", "")) in configured_owner_emails()


def is_company_admin(user=None) -> bool:
    if user is None:
        user = current_user
    return hasattr(user, "has_role") and user.has_role("company_admin")


def is_platform_admin(user=None) -> bool:
    if user is None:
        user = current_user
    return hasattr(user, "has_role") and user.has_role("admin")


def owner_required(f: Callable):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not is_owner():
            flash("این عملیات فقط برای مالک پلتفرم مجاز است.", "danger")
            abort(403)
        return f(*args, **kwargs)

    return decorated


def permission_required(
    permission: str, *, allow_owner: bool = True, allow_company_admin: bool = True
):
    """
    Decorator to check permissions:
    - precedence: owner -> company_admin -> user's has_permission
    - logs details for easier debugging
    """
    permission = (permission or "").strip().lower()

    def decorator(f: Callable):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("لطفاً ابتدا وارد شوید.", "warning")
                abort(403)

            # owner bypass
            if allow_owner and is_owner():
                return f(*args, **kwargs)

            # company_admin bypass
            if allow_company_admin and is_company_admin():
                return f(*args, **kwargs)

            # check user's explicit permission
            if permission and hasattr(current_user, "has_permission") and callable(
                current_user.has_permission
            ):
                if current_user.has_permission(permission):
                    return f(*args, **kwargs)

            # detailed log
            current_app.logger.warning(
                "Permission denied | user=%s | email=%s | required=%s | roles=%s | is_owner=%s | is_company_admin=%s",
                getattr(current_user, "id", None),
                getattr(current_user, "email", None),
                permission,
                [getattr(r, "name", None) for r in getattr(current_user, "roles", [])],
                is_owner(),
                is_company_admin(),
            )

            flash(f"شما اجازه انجام این عملیات را ندارید ({permission}).", "danger")
            abort(403)

        return wrapper

    return decorator


def ensure_rbac_seed(
    *, update_existing: bool = True, force_update_permissions: bool = True
) -> None:
    """
    Ensure base RBAC roles exist in the database.
    - update_existing: if True, update title/description for existing roles
    - force_update_permissions: if True, overwrite permissions on existing roles
    """
    from pms_app.models.role import Role

    try:
        for role_data in _DEFAULT_ROLES:
            name = (role_data.get("name") or "").strip().lower()
            if not name:
                continue

            role = Role.query.filter(func.lower(Role.name) == name).one_or_none()
            permissions = role_data.get("permissions", "") or ""

            if role is None:
                role = Role(
                    name=name,
                    title=role_data.get("title", name.title()),
                    description=role_data.get("description", "") or None,
                    permissions=permissions,
                )
                db.session.add(role)
            else:
                if update_existing:
                    role.title = role_data.get("title") or role.title
                    role.description = role_data.get("description") or role.description
                    if force_update_permissions or not role.permissions:
                        role.permissions = permissions

        db.session.commit()
        current_app.logger.info("RBAC seed/update completed successfully")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to seed/update RBAC roles")
        raise
