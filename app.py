# app.py
"""
Main entry point for the Project Agent application.
Handles app creation, logging setup, CLI commands and runtime info.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pms_app import create_app


# ────────────────────────────────────────────────
# Logging Setup
# ────────────────────────────────────────────────

def setup_root_logging() -> None:
    """Configure basic root logger (console output)."""
    root = logging.getLogger()
    if root.handlers:
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def get_logs_directory() -> Path:
    """Determine where log files should be stored (env var > project root/logs)."""
    custom_dir = os.getenv("PMS_LOG_DIR", "").strip()
    if custom_dir:
        path = Path(custom_dir).resolve()
    else:
        path = Path(__file__).parent / "logs"

    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_app_logging(app) -> None:
    """Add rotating file handler to Flask app logger."""
    try:
        log_dir = get_logs_directory()
        log_file = log_dir / "app.log"

        handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,  # 2 MiB
            backupCount=5,
            encoding="utf-8",
            delay=True,
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s  [in %(pathname)s:%(lineno)d]"
            )
        )

        # Avoid duplicate handlers
        if any(
            isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == str(log_file)
            for h in app.logger.handlers
        ):
            return

        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info("Logging to file enabled → %s", log_file)

    except Exception as exc:
        app.logger.exception("Could not setup file logging → using console only.  %s", exc)


# ────────────────────────────────────────────────
# Utility Functions
# ────────────────────────────────────────────────

def ensure_instance_folder(app) -> None:
    """Create Flask instance folder if it doesn't exist (for SQLite, etc)."""
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)


def coerce_bool(value: str | None) -> bool | None:
    """Convert string env var to boolean (or None if invalid)."""
    if value is None:
        return None
    val = value.strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return None


def mask_db_uri(uri: str | None) -> str | None:
    """Mask credentials in database URI for logging."""
    if not uri:
        return uri
    try:
        parts = urlsplit(uri)
        if not parts.netloc or "@" not in parts.netloc:
            return uri

        userinfo, hostinfo = parts.netloc.split("@", 1)
        user = userinfo.split(":", 1)[0] if ":" in userinfo else userinfo
        masked_netloc = f"{user}:***@{hostinfo}"
        return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "<invalid URI>"


def print_runtime_info(app) -> None:
    """Log important runtime configuration."""
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    logger = app.logger
    logger.info("SQLALCHEMY_DATABASE_URI = %s", mask_db_uri(db_uri))
    logger.info("INSTANCE_PATH          = %s", app.instance_path)
    logger.info("APP_ROOT               = %s", app.root_path)
    logger.info("LOG_DIRECTORY          = %s", get_logs_directory())


def run_db_upgrade(app) -> None:
    """Run alembic upgrade head inside app context."""
    try:
        from flask_migrate import upgrade
        with app.app_context():
            upgrade()
    except ImportError:
        app.logger.warning("flask_migrate not installed → skipping DB upgrade")
    except Exception as exc:
        app.logger.exception("Database upgrade failed: %s", exc)


# ────────────────────────────────────────────────
# RBAC Seeder Discovery
# ────────────────────────────────────────────────

def find_rbac_seeder():
    """Try to locate ensure_rbac_seed function in common locations."""
    candidates = [
        ("pms_app.utils.security", "ensure_rbac_seed"),
        ("pms_app.utils.helpers", "ensure_rbac_seed"),
        ("pms_app.blueprints.users.routes", "ensure_rbac_seed"),
        ("pms_app.models.user", "ensure_rbac_seed"),
    ]

    for module_name, func_name in candidates:
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name, None)
            if callable(func):
                return func
        except (ImportError, AttributeError):
            continue
    return None


# ────────────────────────────────────────────────
# App Creation & Startup
# ────────────────────────────────────────────────

setup_root_logging()
app = create_app()  # assuming create_app() can detect env automatically
ensure_instance_folder(app)
configure_app_logging(app)


# ────────────────────────────────────────────────
# CLI Commands
# ────────────────────────────────────────────────

@app.cli.command("init-db")
def init_db_command():
    ensure_instance_folder(app)
    print_runtime_info(app)
    run_db_upgrade(app)
    app.logger.info("Database initialization / upgrade completed.")


@app.cli.command("seed-rbac")
def seed_rbac_command():
    ensure_instance_folder(app)
    print_runtime_info(app)
    run_db_upgrade(app)

    seeder = find_rbac_seeder()
    if not seeder:
        app.logger.error(
            "RBAC seeder function not found. "
            "Expected: ensure_rbac_seed() in utils.security / utils.helpers / blueprints.users.routes / models.user"
        )
        raise SystemExit(1)

    with app.app_context():
        seeder()
    app.logger.info("RBAC roles & permissions seeded successfully.")


# ────────────────────────────────────────────────
# Development Server
# ────────────────────────────────────────────────

if __name__ == "__main__":
    debug = coerce_bool(os.getenv("FLASK_DEBUG")) or \
            (os.getenv("PMS_ENV", "development").lower() != "production")

    host = os.getenv("HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.getenv("PORT", "5000").strip() or "5000")

    ensure_instance_folder(app)

    if coerce_bool(os.getenv("AUTO_DB_UPGRADE", "1" if debug else "0")):
        print_runtime_info(app)
        run_db_upgrade(app)

    app.run(
        debug=debug,
        host=host,
        port=port,
        use_reloader=debug,
    )