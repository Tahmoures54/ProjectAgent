# Path: pms_app/blueprints/daily_reports/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint("daily_reports", __name__, url_prefix="/daily-reports")

from . import routes  # noqa: E402,F401
