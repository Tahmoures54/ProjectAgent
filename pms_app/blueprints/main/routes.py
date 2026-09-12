# Path: pms_app/blueprints/main/routes.py

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Dict, Any

from flask import (
    current_app,
    flash,
    render_template,
    request,
    url_for,
    send_from_directory,
    abort,
    jsonify,
)
from flask_login import current_user, login_required

from pms_app.models.project import Project
from pms_app.models.subscription import Subscription
from pms_app.utils.assistant import answer_question
from pms_app.utils.inbox import (
    accessible_projects_query,
    dashboard_kpis,
    global_search,
    open_concerns_for_dashboard,
    pending_reports_for_dashboard,
)
from pms_app.utils.security import owner_required
from pms_app.utils.jalali import (
    gregorian_to_jalali,
    jalali_to_gregorian_dict,
)
from . import bp
from .forms import PremiumActivateForm, SettingsForm


def _settings_file() -> Path:
    Path(current_app.instance_path).mkdir(parents=True, exist_ok=True)
    return Path(current_app.instance_path) / "settings.json"


def _load_settings() -> Dict[str, Any]:
    p = _settings_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def _save_settings(data: Dict[str, Any]) -> None:
    p = _settings_file()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_user_plan(user) -> str:
    user_plan = "رایگان"

    if not hasattr(user, "company_id") or not user.company_id:
        return user_plan

    subscription = Subscription.query.filter_by(company_id=user.company_id).first()

    if not subscription:
        return user_plan

    active = False
    if hasattr(subscription, "is_active"):
        active = subscription.is_active
    elif hasattr(subscription, "status"):
        active = subscription.status == "active"
    else:
        active = True

    if not active:
        return user_plan

    if hasattr(subscription, "plan_name") and subscription.plan_name:
        user_plan = subscription.plan_name
    elif hasattr(subscription, "plan") and subscription.plan:
        if isinstance(subscription.plan, str):
            user_plan = subscription.plan
        elif hasattr(subscription.plan, "name"):
            user_plan = subscription.plan.name
        else:
            user_plan = "پلن فعال"
    else:
        user_plan = "پلن فعال"

    return user_plan


def _fa_digits(value) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


@bp.route("/")
def home():
    raw = current_app.config.get("FREE_DAYS") or os.getenv("FREE_DAYS", "90")
    try:
        free_days = max(int(raw), 1)
    except (TypeError, ValueError):
        free_days = 90
    return render_template(
        "main/home.html",
        free_days=free_days,
        free_days_fa=_fa_digits(free_days),
    )


@bp.route("/dashboard")
@login_required
def dashboard():
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config.get("PER_PAGE", 20)

    query = accessible_projects_query(current_user)
    if not current_user.is_owner and not getattr(current_user, "company_id", None):
        flash("حساب شما به شرکتی متصل نیست.", "warning")

    query = query.order_by(Project.updated_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    kpis = dashboard_kpis(current_user)

    return render_template(
        "main/dashboard.html",
        projects=pagination.items,
        pagination=pagination,
        total_projects=kpis["total_projects"],
        total_contracts=kpis["total_contracts"],
        ongoing_projects=kpis["ongoing_projects"],
        delayed_projects=kpis["delayed_projects"],
        pending_reports_count=kpis["pending_reports"],
        open_concerns_count=kpis["open_concerns"],
        critical_concerns_count=kpis["critical_concerns"],
        pending_reports=pending_reports_for_dashboard(current_user),
        open_concerns=open_concerns_for_dashboard(current_user),
        user_plan=_get_user_plan(current_user),
    )


@bp.route("/search")
@login_required
def search():
    q = (request.args.get("q") or "").strip()
    results = global_search(current_user, q)
    return render_template("main/search.html", q=q, results=results)


@bp.route("/assistant/ask", methods=["POST"])
def assistant_ask():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("q") or request.form.get("q") or "").strip()
    return jsonify(answer_question(question))


@bp.route("/about")
def about():
    return render_template("main/about.html")


@bp.route("/help", endpoint="help")
def help_page():
    return render_template("main/help.html")


@bp.route("/terms-of-service")
def terms_of_service():
    return render_template("main/terms_of_service.html")


@bp.route("/privacy-policy")
def privacy_policy():
    return render_template("main/privacy_policy.html")


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@owner_required
def settings():
    form = SettingsForm()
    data = _load_settings()

    if request.method == "GET":
        form.document_types.data = data.get("document_types", "")
        form.disciplines.data = data.get("disciplines", "")
        form.companies.data = data.get("companies", "")
        form.task_statuses.data = data.get("task_statuses", "")

    if form.validate_on_submit():
        new_data = {
            "document_types": (form.document_types.data or "").strip(),
            "disciplines": (form.disciplines.data or "").strip(),
            "companies": (form.companies.data or "").strip(),
            "task_statuses": (form.task_statuses.data or "").strip(),
        }
        _save_settings(new_data)
        flash("تنظیمات با موفقیت ذخیره شد.", "success")

    return render_template("main/settings.html", form=form)


@bp.route("/premium-activate", methods=["GET", "POST"])
@login_required
def premium_activate():
    form = PremiumActivateForm()
    if form.validate_on_submit():
        flash("کلید بررسی شد (این فقط یک نمونه است).", "info")
    return render_template("main/premium_activate.html", form=form)


# ═══════════════════════════════════════════════════════════════════════════
# 📅 تبدیل تاریخ میلادی ↔ خورشیدی
# ═══════════════════════════════════════════════════════════════════════════

@bp.route("/api/date/to-jalali")
def api_to_jalali():
    """
    تبدیل تاریخ میلادی به خورشیدی.

    مثال:
      GET /api/date/to-jalali?date=2024-09-19
      → {"ok": true, "jalali": {"year": 1403, "month": 6, "day": 29, "iso": "1403/06/29", ...}}
    """
    raw = (request.args.get("date") or "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "پارامتر date الزامی است (مثلاً 2024-09-19)"}), 400

    result = gregorian_to_jalali(raw)
    if result is None:
        return jsonify({"ok": False, "error": "تاریخ میلادی نامعتبر است"}), 400

    return jsonify({"ok": True, "jalali": result})


@bp.route("/api/date/to-gregorian")
def api_to_gregorian():
    """
    تبدیل تاریخ خورشیدی به میلادی.

    مثال:
      GET /api/date/to-gregorian?date=1403/06/29
      → {"ok": true, "gregorian": {"year": 2024, "month": 9, "day": 19, "iso": "2024-09-19"}}
    """
    raw = (request.args.get("date") or "").strip()
    if not raw:
        return jsonify({"ok": False, "error": "پارامتر date الزامی است (مثلاً 1403/06/29)"}), 400

    result = jalali_to_gregorian_dict(raw)
    if result is None:
        return jsonify({"ok": False, "error": "تاریخ خورشیدی نامعتبر است"}), 400

    return jsonify({"ok": True, "gregorian": result})


@bp.route("/test-images")
def test_images():
    if not current_app.debug:
        abort(404)
    static_folder = current_app.static_folder
    hero_path = os.path.join(static_folder, "img", "hero") if static_folder else None

    info = {
        "static_folder": static_folder,
        "static_folder_exists": os.path.exists(static_folder) if static_folder else False,
        "hero_path": hero_path,
        "hero_path_exists": os.path.exists(hero_path) if hero_path else False,
        "hero_files": [],
        "all_img_files": [],
    }

    if hero_path and os.path.exists(hero_path):
        info["hero_files"] = os.listdir(hero_path)

    if static_folder:
        img_path = os.path.join(static_folder, "img")
        if os.path.exists(img_path):
            for root, dirs, files in os.walk(img_path):
                for f in files:
                    rel_path = os.path.relpath(os.path.join(root, f), static_folder)
                    info["all_img_files"].append(rel_path.replace("\\", "/"))

    return render_template("main/test_images.html", info=info)


@bp.route("/debug-static")
def debug_static():
    if not current_app.debug:
        abort(404)
    static_folder = current_app.static_folder
    hero_path = os.path.join(static_folder, "img", "hero") if static_folder else None

    result = {
        "static_folder": static_folder,
        "static_url_path": current_app.static_url_path,
        "hero_path": hero_path,
        "hero_exists": os.path.exists(hero_path) if hero_path else False,
        "files": [],
        "urls": [],
    }

    if hero_path and os.path.exists(hero_path):
        files = os.listdir(hero_path)
        result["files"] = files
        result["urls"] = [url_for("static", filename=f"img/hero/{f}") for f in files]

    return jsonify(result)


@bp.route("/serve-img/<path:filename>")
def serve_image(filename: str):
    if not current_app.static_folder:
        abort(404)

    img_folder = os.path.join(current_app.static_folder, "img")
    img_root = os.path.abspath(img_folder)
    full_path = os.path.abspath(os.path.join(img_folder, filename))

    try:
        if os.path.commonpath([img_root, full_path]) != img_root:
            abort(403)
    except ValueError:
        abort(403)

    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        abort(404)

    directory = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)

    return send_from_directory(directory, file_name)
