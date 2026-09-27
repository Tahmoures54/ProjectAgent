from __future__ import annotations

from flask import Blueprint

bp = Blueprint("daily_reports", __name__, url_prefix="/daily-reports")

from . import routes  # noqa: E402,F401
from . import alerts  # noqa: E402,F401
