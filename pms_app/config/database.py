# Path: pms_app/config/database.py
from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.pool import NullPool

# Query keys that break libpq / PgBouncer (Neon pooler, Prisma URLs).
_DROP_QUERY_KEYS = {"channel_binding", "pgbouncer"}


def is_vercel() -> bool:
    return (os.getenv("VERCEL") or "").strip() == "1" or bool(os.getenv("VERCEL_ENV"))


def is_postgres_url(url: str | None) -> bool:
    scheme = ((url or "").split("://", 1)[0] or "").lower()
    return scheme.startswith("postgres")


def normalize_database_url(url: str | None) -> str | None:
    raw = (url or "").strip().strip('"').strip("'")
    if not raw:
        return None

    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]

    scheme, sep, rest = raw.partition("://")
    if sep and scheme == "postgresql":
        raw = "postgresql+psycopg2://" + rest

    parts = urlsplit(raw)
    if parts.scheme.startswith("postgresql"):
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in _DROP_QUERY_KEYS
        ]
        keys = {key.lower() for key, _ in query}
        host = (parts.hostname or "").lower()
        needs_ssl = is_vercel() or "neon.tech" in host or "vercel-storage" in host
        if needs_ssl and "sslmode" not in keys:
            query.append(("sslmode", "require"))
        raw = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return raw


def resolve_database_url() -> str | None:
    for key in ("DATABASE_URL", "POSTGRES_URL", "SQLALCHEMY_DATABASE_URI"):
        value = os.getenv(key)
        if value and value.strip():
            return normalize_database_url(value)
    return None


def vercel_engine_options() -> dict:
    return {
        "poolclass": NullPool,
        "pool_pre_ping": True,
    }
