from __future__ import annotations

import inspect
import os
import sys
import logging
from pathlib import Path

from flask import Flask, jsonify


def create_app(config_name: str | None = None, env: str | None = None) -> Flask:
    instance_path = "/tmp/instance" if os.getenv("VERCEL") == "1" else None
    app = Flask(__name__, instance_relative_config=True, instance_path=instance_path)

    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass

    cfg = (
        config_name
        or env
        or os.getenv("PMS_ENV")
        or os.getenv("FLASK_ENV")
        or ("production" if os.getenv("VERCEL") == "1" else "development")
    ).strip().lower()

    _setup_logging(app)

    if cfg == "production":
        app.config.from_object("pms_app.config.production.ProductionConfig")
    elif cfg == "testing":
        app.config.from_object("pms_app.config.testing.TestingConfig")
    else:
        app.config.from_object("pms_app.config.development.DevelopmentConfig")

    _apply_runtime_database_config(app)

    from . import extensions as ext

    init_extensions = getattr(ext, "init_extensions", None)
    if callable(init_extensions):
        init_extensions(app)
    else:
        for name, obj in vars(ext).items():
            if name.startswith("_"):
                continue
            if inspect.ismodule(obj) or inspect.isfunction(obj) or inspect.isclass(obj):
                continue
            init_app = getattr(obj, "init_app", None)
            if callable(init_app):
                init_app(app)

    import pms_app.models  # noqa: F401

    # Jalali + other template filters
    try:
        from pms_app.utils.template_filters import register_template_filters
        register_template_filters(app)
    except Exception:
        app.logger.exception("Failed to register template filters")

    _ensure_db_schema_and_seed(app, cfg=cfg)
    _register_blueprints(app)
    _register_security_headers(app)
    _register_health_check(app)
    _register_error_handlers(app)
    _register_context_processors(app)
    _ensure_debug_routes(app)
    _ensure_root_route(app)
    _warn_insecure_secret(app, cfg=cfg)

    return app


def _apply_runtime_database_config(app: Flask) -> None:
    """Resolve DB URL after dotenv load so Vercel dashboard vars win, and never crash import."""
    from pms_app.config.database import (
        is_postgres_url,
        is_vercel,
        resolve_database_url,
        vercel_engine_options,
    )

    db_url = resolve_database_url()
    if db_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    if not is_vercel():
        return

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = vercel_engine_options()
    if is_postgres_url(app.config.get("SQLALCHEMY_DATABASE_URI")):
        return

    app.config["SERVERLESS_DB_MISSING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.logger.error(
        "DATABASE_URL / POSTGRES_URL is missing on Vercel. "
        "Set it in Project Settings → Environment Variables."
    )
    _register_missing_database_guard(app)


def _register_missing_database_guard(app: Flask) -> None:
    @app.before_request
    def _vercel_requires_postgres():
        from flask import Response, request

        if (request.path or "").startswith("/static"):
            return None
        payload = {
            "status": "misconfigured",
            "database": "missing",
            "error": "DATABASE_URL is not set on Vercel.",
        }
        if request.path == "/health" or (request.path or "").startswith("/api/"):
            return jsonify(payload), 503
        return Response(
            """<!doctype html>
<html lang="fa" dir="rtl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>پیکربندی ناقص</title></head>
<body style="font-family: Tahoma, sans-serif; padding: 2rem; line-height: 1.9; max-width: 40rem;">
  <h1>دیتابیس روی Vercel تنظیم نشده</h1>
  <p>فایل <code>.env</code> در گیت نیست و روی Vercel اعمال نمی‌شود. در
  <strong>Project Settings → Environment Variables</strong> این متغیرها را برای Production بگذارید:</p>
  <ul>
    <li><code>DATABASE_URL</code> یا <code>POSTGRES_URL</code> — آدرس PostgreSQL (مثلاً Neon)</li>
    <li><code>SECRET_KEY</code> — رشته تصادفی بلند</li>
    <li><code>PMS_ENV=production</code></li>
    <li><code>OWNER_EMAIL</code></li>
  </ul>
</body></html>""",
            status=503,
            mimetype="text/html; charset=utf-8",
        )


def _setup_logging(app: Flask) -> None:
    app.logger.handlers.clear()

    if os.getenv("VERCEL") == "1":
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
        )
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
    else:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
            )
            file_handler.setFormatter(formatter)
            app.logger.addHandler(file_handler)
            app.logger.setLevel(logging.INFO)
        except OSError:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.INFO)
            app.logger.addHandler(handler)


def _is_debug(app: Flask) -> bool:
    return bool(app.config.get("DEBUG", False))


def _warn_insecure_secret(app: Flask, *, cfg: str) -> None:
    key = (app.config.get("SECRET_KEY") or "").strip()
    weak = {"", "dev-secret-change-me", "change-me-to-a-strong-secret", "replace-with-a-secure-secret-key"}
    if cfg == "production" and key in weak:
        app.logger.error(
            "INSECURE SECRET_KEY in production! Set a strong random SECRET_KEY in environment."
        )


def _register_security_headers(app: Flask) -> None:
    """OWASP-aligned security headers for production readiness."""

    @app.after_request
    def _set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        if not app.config.get("DEBUG"):
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        # Avoid caching authenticated HTML by default
        if response.content_type and "text/html" in response.content_type:
            response.headers.setdefault("Cache-Control", "no-store")
        return response


def _register_health_check(app: Flask) -> None:
    @app.get("/health")
    def health():
        """Liveness/readiness for Docker, k8s, load balancers."""
        status = {"status": "ok", "app": app.config.get("APP_NAME", "Project Agent")}
        try:
            from pms_app.extensions import db
            from sqlalchemy import text

            db.session.execute(text("SELECT 1"))
            status["database"] = "ok"
            code = 200
        except Exception as exc:
            status["status"] = "degraded"
            status["database"] = "error"
            if app.debug or app.config.get("TESTING"):
                status["detail"] = str(exc)[:200]
            code = 503
        return jsonify(status), code


def _register_error_handlers(app: Flask) -> None:
    try:
        from pms_app.middleware.error_handler import ErrorHandler

        ErrorHandler(app)
    except Exception:
        app.logger.exception("Failed to register error handlers")


def _register_context_processors(app: Flask) -> None:
    @app.context_processor
    def inject_nav_inbox():
        empty = {"count": 0, "entries": []}
        try:
            from flask_login import current_user

            if not getattr(current_user, "is_authenticated", False):
                return {"nav_inbox": empty}
            from flask import current_app as flask_app

            if flask_app.config.get("SERVERLESS_DB_MISSING"):
                return {"nav_inbox": empty}
            from pms_app.utils.inbox import user_inbox

            return {"nav_inbox": user_inbox(current_user, limit=6)}
        except Exception:
            return {"nav_inbox": empty}


def _ensure_db_schema_and_seed(app: Flask, *, cfg: str) -> None:
    """
    Bootstrap an empty database for local/dev.

    Schema changes on an existing database must go through Alembic.
    Production never auto-creates unless PMS_AUTO_CREATE_DB=1 — except on
    Vercel, where an empty or incomplete Postgres must still boot signup.
    """
    if app.config.get("TESTING") is True:
        return

    if app.config.get("SERVERLESS_DB_MISSING"):
        return

    from pms_app.config.database import is_vercel

    auto_flag = (os.getenv("PMS_AUTO_CREATE_DB") or "").strip().lower()
    force_auto = auto_flag in {"1", "true", "yes", "on"}
    on_vercel = is_vercel()

    should_run = force_auto or (cfg != "production") or on_vercel
    if not should_run:
        return

    try:
        from sqlalchemy import inspect as sa_inspect
        from pms_app.extensions import db
        from pms_app.utils.security import ensure_rbac_seed

        with app.app_context():
            inspector = sa_inspect(db.engine)
            existing_tables = set(inspector.get_table_names())
            expected = set(db.metadata.tables.keys())
            missing = expected - existing_tables
            empty = not existing_tables or existing_tables == {"alembic_version"}

            if empty:
                app.logger.warning(
                    "Database is empty (tables=%s). Running db.create_all() ...",
                    sorted(existing_tables),
                )
                db.create_all()
            elif missing and (force_auto or on_vercel):
                app.logger.warning(
                    "Creating missing tables %s (serverless/auto bootstrap).",
                    sorted(missing),
                )
                db.create_all()
            elif missing:
                app.logger.error(
                    "Missing tables %s. Run Alembic migrations; create_all is not used on non-empty databases.",
                    sorted(missing),
                )

            ensure_rbac_seed()

    except Exception:
        app.logger.exception("Failed to ensure DB schema / RBAC seed")
        if _is_debug(app):
            raise


def _register_blueprints(app: Flask) -> None:
    from pms_app.blueprints import get_blueprints

    registered_total = 0
    for bp in get_blueprints():
        app.register_blueprint(bp)
        registered_total += 1
        app.logger.info(
            "Registered blueprint: name=%s url_prefix=%s",
            bp.name,
            bp.url_prefix,
        )
    app.logger.info("Total registered blueprints: %s", registered_total)


def _ensure_root_route(app: Flask) -> None:
    has_root = any(rule.rule == "/" for rule in app.url_map.iter_rules())
    if has_root:
        return

    @app.get("/")
    def _index_fallback():
        try:
            from flask import render_template
            return render_template("main/home.html")
        except Exception:
            rules = sorted({rule.rule for rule in app.url_map.iter_rules()})
            return (
                "App is running, but no '/' route was registered.<br>"
                "Available routes:<br><pre>"
                + "\n".join(rules)
                + "</pre>",
                200,
            )


def _ensure_debug_routes(app: Flask) -> None:
    if not _is_debug(app):
        return

    @app.get("/__routes")
    def _routes():
        rules = []
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
            methods = ",".join(
                sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
            )
            rules.append(
                f"{rule.rule:30s}  [{methods:10s}]  -> {rule.endpoint}"
            )
        return "<pre>" + "\n".join(rules) + "</pre>", 200
