# Path: pms_app/models/user.py
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.associationproxy import association_proxy
from flask_login import UserMixin

from pms_app.extensions import check_password_hash, db, generate_password_hash, login_manager
from pms_app.models.association import user_roles


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    e = str(email).strip().lower()
    return e or None


class User(db.Model, UserMixin):
    """
    3 نوع کاربر اصلی:
    1) Owner (مالک سایت) → دسترسی کامل به همه چیز
    2) Company Admin → مدیر شرکت (دسترسی به همه پروژه‌های شرکت + مدیریت کاربران شرکت)
    3) Company User → کاربر عادی شرکت (دسترسی فقط به پروژه‌هایی که عضو آن‌هاست)
    """
    __tablename__ = "users"

    __table_args__ = (
        db.Index("ix_users_phone", "phone"),
        db.Index("ix_users_phone_verified", "phone_verified"),
        db.Index("ix_users_sms_opt_in", "sms_opt_in"),
        db.Index("ix_users_company_id", "company_id"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Tenant / Company
    company_id = db.Column(
        db.Integer,
        db.ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )

    # پروفایل
    full_name = db.Column(db.String(120), nullable=True)
    company_name = db.Column(db.String(120), nullable=True)

    # شماره موبایل برای SMS
    phone = db.Column(db.String(32), nullable=True)
    phone_verified = db.Column(db.Boolean, nullable=False, default=False)
    phone_verified_at = db.Column(db.DateTime, nullable=True)
    sms_opt_in = db.Column(db.Boolean, nullable=False, default=True)

    # احراز هویت
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # وضعیت
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(64), nullable=True)
    last_login_user_agent = db.Column(db.String(255), nullable=True)

    # 2FA
    two_fa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    two_fa_secret = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    # ──────────────────────────────────────────────
    # Relationships
    # ──────────────────────────────────────────────

    company = db.relationship(
        "Company",
        back_populates="users",
        foreign_keys=[company_id],
        lazy="joined",
    )

    created_companies = db.relationship(
        "Company",
        back_populates="created_by",
        foreign_keys="Company.created_by_user_id",
        lazy="dynamic",
    )

    roles = db.relationship(
        "Role",
        secondary=user_roles,
        back_populates="users",
        lazy="joined",
    )

    # projects از طریق ProjectMembership (association object) ایجاد می‌شود
    # ProjectMembership با backref نام 'project_memberships' را روی User می‌سازد.
    projects = association_proxy("project_memberships", "project")

    # ──────────────────────────────────────────────
    # Password methods
    # ──────────────────────────────────────────────

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw or "")

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw or "")

    # ──────────────────────────────────────────────
    # Roles & Permissions
    # ──────────────────────────────────────────────

    def role_names(self) -> set[str]:
        return {str(r.name).strip().lower() for r in (self.roles or []) if r and r.name}

    def has_role(self, role_name: str) -> bool:
        role_name = (role_name or "").strip().lower()
        return role_name in self.role_names()

    @property
    def is_owner_by_email(self) -> bool:
        try:
            from pms_app.utils.security import configured_owner_emails
            return normalize_email(self.email) in configured_owner_emails()
        except Exception:
            return False

    @property
    def is_owner(self) -> bool:
        return self.has_role("owner") or self.is_owner_by_email

    @property
    def is_company_admin(self) -> bool:
        return self.has_role("company_admin")

    @property
    def is_company_user(self) -> bool:
        return self.has_role("company_user")

    @property
    def is_admin(self) -> bool:
        return self.is_owner or self.is_company_admin

    def has_permission(self, perm: str) -> bool:
        if not perm:
            return False
        if self.is_owner:
            return True
        for r in (self.roles or []):
            if r and r.has_permission(perm):
                return True
        return False

    # ──────────────────────────────────────────────
    # Project-level access helpers (جدید)
    # ──────────────────────────────────────────────

    @property
    def active_projects(self):
        """پروژه‌های فعال که کاربر عضو آن‌هاست"""
        from pms_app.models.project_membership import ProjectMembership
        return (
            ProjectMembership.query
            .filter_by(user_id=self.id, status="active")
            .join("project")
        )

    @property
    def project_count(self) -> int:
        """تعداد پروژه‌های فعال کاربر"""
        from pms_app.models.project_membership import ProjectMembership
        return (
            ProjectMembership.query
            .filter_by(user_id=self.id, status="active")
            .count()
        )

    def is_member_of(self, project) -> bool:
        """آیا کاربر عضو فعال این پروژه است؟"""
        if not project or not project.id:
            return False
        from pms_app.models.project_membership import ProjectMembership
        return (
            ProjectMembership.query.filter_by(
                project_id=project.id,
                user_id=self.id,
                status="active",
            ).first()
            is not None
        )

    def can_access_project(self, project) -> bool:
        """
        آیا کاربر اجازه دسترسی به این پروژه را دارد؟
        منطق اولویت‌دار:
        1. Owner پلتفرم → همیشه بله
        2. اگر پروژه متعلق به شرکت کاربر نباشد → خیر
        3. Company Admin → بله (برای تمام پروژه‌های شرکت خودش)
        4. کاربران عادی → فقط اگر عضو پروژه باشند
        """
        if not project or not project.company_id:
            return False

        if self.is_owner:
            return True

        # پروژه باید متعلق به شرکت کاربر باشد
        if self.company_id != project.company_id:
            return False

        if self.is_company_admin:
            return True

        # کاربر عادی → فقط عضویت مستقیم
        return self.is_member_of(project)

    # ──────────────────────────────────────────────
    # Company-scope helpers
    # ──────────────────────────────────────────────

    def can_manage_user(self, target: "User") -> bool:
        if not target:
            return False
        if self.is_owner:
            return True
        if self.is_company_admin:
            if self.company_id is None or target.company_id is None:
                return False
            if self.company_id != target.company_id:
                return False
            if target.is_owner:
                return False
            return True
        return False

    # ──────────────────────────────────────────────
    # SMS helpers
    # ──────────────────────────────────────────────

    @property
    def phone_normalized(self) -> Optional[str]:
        if not self.phone:
            return None
        try:
            from pms_app.utils.sms import normalize_phone
            return normalize_phone(self.phone)
        except Exception:
            return self.phone.strip() if isinstance(self.phone, str) else None

    def can_receive_sms(self, *, transactional: bool = True) -> bool:
        if not self.phone or not str(self.phone).strip():
            return False
        if not self.phone_verified:
            return False
        if transactional:
            return True
        return bool(self.sms_opt_in)

    def mark_phone_verified(self) -> None:
        self.phone_verified = True
        self.phone_verified_at = utcnow()

    # ──────────────────────────────────────────────
    # Flask-Login
    # ──────────────────────────────────────────────

    def get_id(self) -> str:
        return str(self.id)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} active={self.is_active} company_id={self.company_id}>"

@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None