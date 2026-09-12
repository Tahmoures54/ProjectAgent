# tests/test_vercel_config.py
from __future__ import annotations

from pms_app.config.database import normalize_database_url, resolve_database_url

def test_development_config_import_on_vercel_without_db_does_not_raise(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    import importlib
    import pms_app.config.development as development

    importlib.reload(development)
    assert development.DevelopmentConfig.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"


def test_normalize_postgres_scheme_and_neon_query():
    url = normalize_database_url(
        "postgres://u:p@ep-x-pooler.c-10.us-east-1.aws.neon.tech/db"
        "?channel_binding=require&sslmode=require&pgbouncer=true"
    )
    assert url is not None
    assert url.startswith("postgresql+psycopg2://")
    assert "channel_binding" not in url
    assert "pgbouncer" not in url
    assert "sslmode=require" in url


def test_resolve_database_url_reads_postgres_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@localhost:5432/app")
    assert resolve_database_url() == "postgresql+psycopg2://u:p@localhost:5432/app"


def test_vercel_boot_without_database_url_does_not_crash(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("PMS_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "vercel-test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)

    from pms_app import create_app

    app = create_app()
    assert app.config.get("SERVERLESS_DB_MISSING") is True
    client = app.test_client()
    home = client.get("/")
    assert home.status_code == 503
    assert "DATABASE_URL" in home.get_data(as_text=True)
    health = client.get("/health")
    assert health.status_code == 503
    assert health.get_json()["database"] == "missing"
