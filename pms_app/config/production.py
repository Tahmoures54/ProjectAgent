# Path: pms_app/config/production.py
from __future__ import annotations

import os

from .base import BaseConfig
from .database import is_postgres_url, is_vercel, resolve_database_url, vercel_engine_options


class ProductionConfig(BaseConfig):
    DEBUG = False
    TESTING = False

    _prod_db_uri = resolve_database_url()
    if is_postgres_url(_prod_db_uri):
        SQLALCHEMY_DATABASE_URI = _prod_db_uri
    elif is_vercel():
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    # Harden cookies
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Prefer strong SECRET_KEY from env (BaseConfig already reads it)
    # WTF CSRF
    WTF_CSRF_TIME_LIMIT = int(os.getenv("WTF_CSRF_TIME_LIMIT", "3600"))

    if is_vercel():
        SQLALCHEMY_ENGINE_OPTIONS = vercel_engine_options()
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        }
