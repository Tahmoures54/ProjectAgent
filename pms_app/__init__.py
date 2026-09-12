from __future__ import annotations

import inspect
import os
import sys
import logging
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules

from flask import Blueprint, Flask, jsonify


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
            from pms_app.utils.inbox import user_inbox

            return {"nav_inbox": user_inbox(current_user, limit=6)}
        except Exception:
            return {"nav_inbox": empty}


def _ensure_db_schema_and_seed(app: Flask, *, cfg: str) -> None:
    """
    Ensure schema exists for real data.
    - Empty DB → create_all
    - Existing DB with missing tables (e.g. daily_reports, concerns) → create missing only
    Production: only if PMS_AUTO_CREATE_DB=1 (prefer Alembic migrations)
    """
    if app.config.get("TESTING") is True:
        return

    auto_flag = (os.getenv("PMS_AUTO_CREATE_DB") or "").strip().lower()
    force_auto = auto_flag in {"1", "true", "yes", "on"}

    should_run = force_auto or (cfg != "production")
    if not should_run:
        return

    try:
        from sqlalchemy import inspect as sa_inspect
        from pms_app.extensions import db
        from pms_app.utils.security import ensure_rbac_seed

        with app.app_context():
            inspector = sa_inspect(db.engine)
            existing_tables = set(inspector.get_table_names())

            # All model tables registered on metadata
            expected = set(db.metadata.tables.keys())
            missing = expected - existing_tables

            if not existing_tables or existing_tables == {"alembic_version"}:
                app.logger.warning(
                    "Database is empty (tables=%s). Running db.create_all() ...",
                    sorted(existing_tables),
                )
                db.create_all()
            elif missing:
                app.logger.warning(
                    "Missing tables detected: %s — creating them via create_all (checkfirst=True)",
                    sorted(missing),
                )
                db.create_all()

            ensure_rbac_seed()

    except Exception:
        app.logger.exception("Failed to ensure DB schema / RBAC seed")
        if _is_debug(app):
            raise


def _register_blueprints(app: Flask) -> None:
    from . import blueprints as bp_pkg

    registered_total = 0

    for m in iter_modules(bp_pkg.__path__):
        bp_name = m.name
        if bp_name.startswith("_"):
            continue

        module = None
        last_exc: Exception | None = None

        for mod_path in (
            f"pms_app.blueprints.{bp_name}.routes",
            f"pms_app.blueprints.{bp_name}",
        ):
            try:
                module = import_module(mod_path)
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                app.logger.exception("Blueprint import failed: %s", mod_path)

        if module is None:
            if _is_debug(app) and last_exc is not None:
                raise last_exc
            continue

        blueprints = [v for v in vars(module).values() if isinstance(v, Blueprint)]

        for attr in ("bp", "blueprint"):
            v = getattr(module, attr, None)
            if isinstance(v, Blueprint) and v not in blueprints:
                blueprints.append(v)

        if not blueprints:
            app.logger.warning(
                "No Blueprint object found for '%s' in %s",
                bp_name,
                module.__name__,
            )
            continue

        for bp in blueprints:
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
