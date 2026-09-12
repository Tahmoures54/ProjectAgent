from __future__ import annotations

from .base import BaseConfig, _normalize_sqlite_uri
from .database import is_postgres_url, is_vercel, resolve_database_url


class DevelopmentConfig(BaseConfig):
    DEBUG = True

    _dev_db_uri = resolve_database_url()

    if is_vercel():
        # Importing this class must never raise: config/__init__.py loads it
        # even when create_app selects ProductionConfig.
        SQLALCHEMY_DATABASE_URI = _dev_db_uri if is_postgres_url(_dev_db_uri) else "sqlite:///:memory:"
    elif _dev_db_uri and is_postgres_url(_dev_db_uri):
        SQLALCHEMY_DATABASE_URI = _dev_db_uri
    elif _dev_db_uri:
        SQLALCHEMY_DATABASE_URI = _normalize_sqlite_uri(BaseConfig.PROJECT_DIR, _dev_db_uri)
    else:
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{BaseConfig.DB_PATH.as_posix()}"
