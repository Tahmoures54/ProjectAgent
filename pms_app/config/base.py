from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _normalize_sqlite_uri(project_root: Path, uri: str) -> str:
    uri = (uri or "").strip()

    if uri.startswith("sqlite:///"):
        raw_path = uri[len("sqlite:///") :]

        is_abs = bool(re.match(r"^[A-Za-z]:[\\/]", raw_path)) or raw_path.startswith("/")
        if is_abs:
            return uri

        abs_path = (project_root / raw_path).resolve()
        return f"sqlite:///{abs_path.as_posix()}"

    return uri


class BaseConfig:

    PROJECT_DIR = Path(__file__).resolve().parents[2]
    INSTANCE_DIR = PROJECT_DIR / "instance"

    # در Vercel ممکن است نتوانیم پوشه instance را بسازیم، پس خطا را می‌گیریم
    try:
        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    DB_PATH = INSTANCE_DIR / "pms.db"

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # -------------------------------------------------
    # Database (ایمن‌سازی شده برای Vercel و Local)
    # -------------------------------------------------
    _env_db_uri = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")

    if _env_db_uri and _env_db_uri.startswith("postgresql"):
        # اگر روی ورسل یا تست پستگرس بودیم
        SQLALCHEMY_DATABASE_URI = _env_db_uri
    else:
        # در محیط محلی اگر SQLITE تنظیم شده بود آن را نرمالایز کن، وگرنه از پیش‌فرض استفاده کن
        local_sqlite = _env_db_uri or f"sqlite:///{DB_PATH.as_posix()}"
        SQLALCHEMY_DATABASE_URI = _normalize_sqlite_uri(PROJECT_DIR, local_sqlite)

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # -------------------------------------------------
    # Owner
    # -------------------------------------------------
    OWNER_EMAIL = os.getenv("OWNER_EMAIL", "").strip().lower()
    OWNER_EMAILS = os.getenv("OWNER_EMAILS", "").strip().lower()

    # -------------------------------------------------
    # Application Branding
    # -------------------------------------------------
    APP_NAME = os.getenv("APP_NAME", "Project Agent")
    APP_YEAR = os.getenv("APP_YEAR", "۱۴۰۴")

    # -------------------------------------------------
    # Misc
    # -------------------------------------------------
    REMEMBER_COOKIE_DURATION = timedelta(
        days=int(os.getenv("REMEMBER_COOKIE_DAYS", "30"))
    )

    DEV_EMAIL_CONSOLE = _as_bool(
        os.getenv("DEV_EMAIL_CONSOLE"),
        default=True
    )

    PER_PAGE = int(os.getenv("PER_PAGE", "20"))
    RESET_TOKEN_MAX_AGE_SECONDS = int(
        os.getenv("RESET_TOKEN_MAX_AGE_SECONDS", "3600")
    )
