# Path: pms_app/blueprints/billing/routes.py
from __future__ import annotations

import importlib
import os
from datetime import datetime, timedelta
from typing import Any, Optional, Type
from urllib.parse import urljoin, urlparse

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from pms_app.blueprints.billing import bp
from pms_app.extensions import csrf_exempt, db
from pms_app.models.contract import Contract
from pms_app.models.project import Project
from pms_app.models.subscription import Subscription
from pms_app.models.user import User
from pms_app.utils.security import is_owner, owner_required

# اگر Company / ContractItem وجود داشته باشند (سناریوی multi-tenant)
try:  # pragma: no cover
    from pms_app.models.company import Company  # type: ignore
except Exception:  # pragma: no cover
    Company = None  # type: ignore

try:  # pragma: no cover
    from pms_app.models.item import ContractItem  # type: ignore
except Exception:  # pragma: no cover
    ContractItem = None  # type: ignore


# Stripe
try:
    import stripe  # type: ignore
except ModuleNotFoundError:
    stripe = None  # pragma: no cover


# -------------------------
# Helpers: Monetization knobs
# -------------------------
def _get_free_days() -> int:
    raw = current_app.config.get("FREE_DAYS") or os.getenv("FREE_DAYS", "90")
    try:
        days = int(raw)
    except Exception:
        days = 90
    return max(days, 1)


def _get_pro_trial_days() -> int:
    raw = current_app.config.get("PRO_TRIAL_DAYS") or os.getenv("PRO_TRIAL_DAYS", "14")
    try:
        days = int(raw)
    except Exception:
        days = 14
    return max(days, 0)


def _stripe_configured() -> bool:
    return (
        stripe is not None
        and bool(os.getenv("STRIPE_SECRET_KEY"))
        and bool(os.getenv("STRIPE_PRICE_ID_PRO"))
    )


def _stripe_init() -> None:
    if stripe is None:
        raise RuntimeError("stripe package is not installed. Run: pip install stripe")

    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    stripe.api_key = secret


def _is_safe_next_url(target: str) -> bool:
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def _clean_next_url() -> str:
    next_url = request.args.get("next") or request.form.get("next") or ""
    if next_url and not _is_safe_next_url(next_url):
        return ""
    return next_url


# -------------------------
# Tenant helpers
# -------------------------
def _subscription_is_company_based() -> bool:
    return hasattr(Subscription, "company_id")


def _current_company_id() -> Optional[int]:
    """
    سناریوی multi-tenant:
    - user.company_id باید ست باشد (owner می‌تواند None باشد)
    """
    cid = getattr(current_user, "company_id", None)
    try:
        return int(cid) if cid is not None else None
    except Exception:
        return None


def _get_or_create_subscription_for_scope(*, user_id: int, company_id: Optional[int]) -> Subscription:
    """
    Subscription را با توجه به مدل/اسکوپ می‌سازد:
    - اگر Subscription.company_id دارد => company-based
    - وگرنه => legacy user-based
    """
    if _subscription_is_company_based():
        if company_id is None:
            # کاربر بدون شرکت: برای owner مشکلی نیست، برای دیگران باید از paywall عبور نکند
            # یک subscription free برمی‌گردانیم (ایجاد نمی‌کنیم) تا کرش نکند
            sub = Subscription(plan="free", status="active")  # type: ignore[call-arg]
            return sub

        sub = Subscription.query.filter_by(company_id=int(company_id)).one_or_none()  # type: ignore[attr-defined]
        if sub is None:
            # اگر create_free جدید باشد
            try:
                sub = Subscription.create_free(company_id=int(company_id), billing_user_id=int(user_id))  # type: ignore[arg-type]
            except TypeError:
                sub = Subscription(company_id=int(company_id), plan="free", status="active")  # type: ignore[call-arg]
                if hasattr(sub, "billing_user_id"):
                    sub.billing_user_id = int(user_id)

            sub.start_free_period(days=_get_free_days())
            db.session.add(sub)
            db.session.commit()
        return sub

    # legacy user-based
    sub = Subscription.query.filter_by(user_id=int(user_id)).one_or_none()  # type: ignore[attr-defined]
    if sub is None:
        sub = Subscription.create_free(user_id=int(user_id))  # type: ignore[arg-type]
        sub.start_free_period(days=_get_free_days())
        db.session.add(sub)
        db.session.commit()
    return sub


# -------------------------
# Usage helpers (company-aware + fallback)
# -------------------------
def _projects_query_for_current_user():
    """
    - اگر Project.company_id داشته باشد => بر اساس company_id
    - وگرنه => fallback قدیمی (owner_id/user_id/created_by_id)
    """
    q = Project.query
    uid = int(current_user.id)
    cid = _current_company_id()

    if cid is not None and hasattr(Project, "company_id"):
        q = q.filter(Project.company_id == cid)  # type: ignore[attr-defined]
    else:
        if hasattr(Project, "owner_id"):
            q = q.filter(Project.owner_id == uid)  # type: ignore[attr-defined]
        elif hasattr(Project, "user_id"):
            q = q.filter(Project.user_id == uid)  # type: ignore[attr-defined]
        elif hasattr(Project, "created_by_id"):
            q = q.filter(Project.created_by_id == uid)  # type: ignore[attr-defined]

    if hasattr(Project, "is_active"):
        q = q.filter(Project.is_active.is_(True))  # type: ignore[attr-defined]
    elif hasattr(Project, "status"):
        q = q.filter(Project.status.notin_(["closed", "completed", "canceled", "cancelled", "archived"]))  # type: ignore[attr-defined]

    return q


def _compute_usage_for_manage() -> dict:
    """
    usage را برای صفحه manage نشان می‌دهد.
    در حالت multi-tenant این usage برای کل شرکت است.
    """
    usage = {"active_projects": 0, "active_contracts": 0, "active_items": 0}

    try:
        q_projects = _projects_query_for_current_user()
        usage["active_projects"] = int(
            db.session.scalar(select(func.count()).select_from(q_projects.subquery())) or 0
        )

        # اگر Contract.company_id داشته باشد => مستقیم بر اساس company
        cid = _current_company_id()
        if cid is not None and hasattr(Contract, "company_id"):
            cq = Contract.query.filter(Contract.company_id == cid)  # type: ignore[attr-defined]
            if hasattr(Contract, "is_active"):
                cq = cq.filter(Contract.is_active.is_(True))  # type: ignore[attr-defined]
            elif hasattr(Contract, "status"):
                cq = cq.filter(Contract.status.notin_(["closed", "canceled", "cancelled", "terminated", "archived"]))  # type: ignore[attr-defined]
            usage["active_contracts"] = int(cq.count())
        else:
            project_ids = [pid for (pid,) in q_projects.with_entities(Project.id).all()]
            if project_ids and hasattr(Contract, "project_id"):
                cq = Contract.query.filter(Contract.project_id.in_(project_ids))  # type: ignore[attr-defined]
                if hasattr(Contract, "is_active"):
                    cq = cq.filter(Contract.is_active.is_(True))  # type: ignore[attr-defined]
                elif hasattr(Contract, "status"):
                    cq = cq.filter(Contract.status.notin_(["closed", "canceled", "cancelled", "terminated", "archived"]))  # type: ignore[attr-defined]
                usage["active_contracts"] = int(cq.count())

        # Items
        if ContractItem is not None and cid is not None and hasattr(ContractItem, "company_id"):
            iq = ContractItem.query.filter(ContractItem.company_id == cid)  # type: ignore[attr-defined]
            if hasattr(ContractItem, "status"):
                # فقط open-ish ها
                iq = iq.filter(ContractItem.status.notin_(["closed", "canceled", "cancelled", "archived"]))  # type: ignore[attr-defined]
            usage["active_items"] = int(iq.count())
        else:
            # fallback خیلی محافظه‌کارانه (برای پروژه‌هایی که مدل item متفاوت دارند)
            ItemCls = _resolve_model_class(
                "pms_app.models.item",
                preferred_names=["Item", "Items", "ProjectItem", "InventoryItem", "ItemModel", "ContractItem"],
            )
            if ItemCls is not None:
                # اگر company_id دارد
                if cid is not None and hasattr(ItemCls, "company_id"):
                    iq = ItemCls.query.filter(ItemCls.company_id == cid)  # type: ignore[attr-defined]
                    usage["active_items"] = int(iq.count())
    except SQLAlchemyError:
        current_app.logger.exception("DB error while computing usage for billing/manage")
    except Exception:
        current_app.logger.exception("Unexpected error while computing usage for billing/manage")

    return usage


def _resolve_model_class(module_path: str, preferred_names: list[str]) -> Optional[Type]:
    try:
        mod = importlib.import_module(module_path)
    except Exception:
        current_app.logger.exception("Failed to import module: %s", module_path)
        return None

    for name in preferred_names:
        cls = getattr(mod, name, None)
        if cls is not None:
            return cls

    try:
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name, None)
            if isinstance(obj, type):
                try:
                    if hasattr(db, "Model") and issubclass(obj, db.Model):  # type: ignore[arg-type]
                        return obj
                except Exception:
                    continue
    except Exception:
        return None

    return None


# -------------------------
# SMS helpers (Plan activated)
# -------------------------
def _format_date_for_sms(dt: Optional[datetime]) -> str:
    if not dt:
        return "-"
    return dt.strftime("%Y/%m/%d")


def _plan_label_fa(plan: str) -> str:
    p = (plan or "").strip().lower()
    return {
        "free": "رایگان",
        "bronze": "برنزی",
        "silver": "نقره‌ای",
        "gold": "طلایی",
    }.get(p, p or "نامشخص")


def _get_user_phone(user: User) -> Optional[str]:
    for attr in ("mobile", "phone", "phone_number", "mobile_number", "cellphone", "cell"):
        val = getattr(user, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _send_sms_best_effort(to: str, message: str, *, user_id: int, event: str) -> bool:
    try:
        sms_mod = importlib.import_module("pms_app.utils.sms")
    except Exception:
        current_app.logger.exception("SMS module import failed")
        return False

    send_fn = getattr(sms_mod, "send_sms", None) or getattr(sms_mod, "send", None)
    if not callable(send_fn):
        current_app.logger.warning("SMS send function not found in pms_app.utils.sms")
        return False

    try:
        try:
            send_fn(to=to, message=message)  # type: ignore[misc]
        except TypeError:
            try:
                send_fn(to, message)  # type: ignore[misc]
            except TypeError:
                send_fn(receptor=to, text=message)  # type: ignore[misc]
        current_app.logger.info("SMS sent (best-effort). event=%s user_id=%s", event, user_id)
        return True
    except Exception:
        current_app.logger.exception("SMS sending failed. event=%s user_id=%s", event, user_id)
        return False


def _maybe_send_plan_activated_sms(
    *,
    user_id: int,
    previous_plan: Optional[str],
    previous_end: Optional[datetime],
    new_plan: str,
    new_end: Optional[datetime],
) -> None:
    if not bool(current_app.config.get("SMS_BILLING_NOTIFICATIONS_ENABLED", True)):
        return

    np = (new_plan or "").strip().lower()
    pp = (previous_plan or "").strip().lower()

    if np == "free" or not np:
        return

    changed_to_paid = (pp == "free" or not pp) and np in {"bronze", "silver", "gold"}
    extended = False
    try:
        if new_end and (previous_end is None or new_end > previous_end):
            extended = True
    except Exception:
        extended = False

    if not (changed_to_paid or extended):
        return

    user = db.session.get(User, int(user_id))
    if not user:
        return

    phone = _get_user_phone(user)
    if not phone:
        return

    app_name = current_app.config.get("APP_NAME", "Project Agent")
    manage_url = url_for("billing.manage", _external=True)

    msg = (
        f"{app_name}\n"
        f"اشتراک «{_plan_label_fa(np)}» برای شرکت/حساب شما فعال شد.\n"
        f"اعتبار تا: {_format_date_for_sms(new_end)}\n"
        f"مدیریت اشتراک: {manage_url}"
    )

    _send_sms_best_effort(phone, msg, user_id=int(user_id), event="PLAN_ACTIVATED")


# -------------------------
# Stripe object normalization
# -------------------------
def _stripe_to_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            return {}
    try:
        return dict(obj)  # type: ignore[arg-type]
    except Exception:
        return {}


def _update_subscription_from_stripe(subscription_obj: Any, *, user_id: int, company_id: Optional[int]) -> None:
    """
    هماهنگ با پلن‌های جدید:
    - Stripe active/trialing/past_due => silver
    - canceled/unpaid => free
    """
    sub = _get_or_create_subscription_for_scope(user_id=int(user_id), company_id=company_id)

    prev_plan = getattr(sub, "plan", None)
    prev_end = getattr(sub, "current_period_end", None)

    sobj = _stripe_to_dict(subscription_obj)

    stripe_subscription_id = sobj.get("id")
    stripe_customer_id = sobj.get("customer")
    status = (sobj.get("status") or "").strip().lower()
    cancel_at_period_end = bool(sobj.get("cancel_at_period_end", False))
    current_period_end = sobj.get("current_period_end")

    if hasattr(sub, "stripe_subscription_id"):
        sub.stripe_subscription_id = stripe_subscription_id
    if hasattr(sub, "stripe_customer_id"):
        sub.stripe_customer_id = stripe_customer_id
    if status:
        sub.status = status
    sub.cancel_at_period_end = cancel_at_period_end

    if current_period_end:
        try:
            sub.current_period_end = datetime.utcfromtimestamp(int(current_period_end))
        except Exception:
            pass

    if status in {"trialing", "active", "past_due", "incomplete", "incomplete_expired"}:
        sub.plan = "silver"
    if status in {"canceled", "unpaid"}:
        sub.plan = "free"

    # اگر subscription company-based است و billing_user_id دارد، آخرین اقدام‌کننده را ذخیره کنیم
    if _subscription_is_company_based() and hasattr(sub, "billing_user_id"):
        try:
            sub.billing_user_id = int(user_id)
        except Exception:
            pass

    db.session.commit()

    _maybe_send_plan_activated_sms(
        user_id=int(user_id),
        previous_plan=prev_plan,
        previous_end=prev_end,
        new_plan=str(getattr(sub, "plan", "") or ""),
        new_end=getattr(sub, "current_period_end", None),
    )


def _try_sync_from_checkout_session(session_id: str) -> bool:
    if not session_id or not _stripe_configured() or stripe is None:
        return False

    try:
        _stripe_init()
        sess = stripe.checkout.Session.retrieve(
            session_id,
            expand=["subscription", "customer"],
        )
        sess_d = _stripe_to_dict(sess)

        # در سناریوی جدید: client_reference_id = company_id
        cid = _current_company_id()
        client_ref = str(sess_d.get("client_reference_id") or "")

        if _subscription_is_company_based():
            if cid is None or client_ref != str(cid):
                return False
        else:
            # legacy: client_reference_id = user_id
            if client_ref != str(current_user.id):
                return False

        subscription_obj = sess_d.get("subscription")
        if subscription_obj:
            _update_subscription_from_stripe(subscription_obj, user_id=int(current_user.id), company_id=cid)
            return True
    except Exception:
        current_app.logger.exception("Failed to sync subscription from Stripe checkout session_id=%s", session_id)

    return False


# -------------------------
# Paywall
# -------------------------
@bp.before_app_request
def enforce_paywall_after_free_period():
    if not current_user.is_authenticated:
        return None

    if is_owner(current_user):
        return None

    endpoint = request.endpoint or ""
    if not endpoint or endpoint.startswith("static"):
        return None

    ALLOW = {
        "billing.pricing",
        "billing.manage",
        "billing.checkout_pro",
        "billing.success",
        "billing.cancel",
        "billing.portal",
        "billing.webhook",
        "auth.login",
        "auth.login_2fa",
        "auth.logout",
        "auth.forgot_password",
        "auth.reset_password",
        "auth.change_password",
        "auth.register",
        "main.home",
        "main.about",
        "main.help",
        "main.terms_of_service",
        "main.privacy_policy",
    }
    if endpoint in ALLOW:
        return None

    cid = _current_company_id()
    sub = _get_or_create_subscription_for_scope(user_id=int(current_user.id), company_id=cid)

    if hasattr(sub, "needs_payment") and sub.needs_payment():
        next_url = request.full_path if request.full_path else request.path
        flash("دوره رایگان شما پایان یافته است. برای ادامه استفاده، پلن را خریداری کنید.", "warning")
        return redirect(url_for("billing.pricing", next=next_url))

    return None


# -------------------------
# Pages
# -------------------------
@bp.get("/pricing")
def pricing():
    tier = None
    sub = None

    if current_user.is_authenticated:
        cid = _current_company_id()
        sub = _get_or_create_subscription_for_scope(user_id=int(current_user.id), company_id=cid)
        tier = sub.effective_tier() if hasattr(sub, "effective_tier") else None

    next_url = request.args.get("next", "") or ""
    stripe_ready = _stripe_configured()

    return render_template(
        "billing/pricing.html",
        tier=tier,
        sub=sub,
        next=next_url,
        stripe_ready=stripe_ready,
        free_days=_get_free_days(),
        pro_trial_days=_get_pro_trial_days(),
    )


@bp.get("/manage")
@login_required
def manage():
    cid = _current_company_id()
    sub = _get_or_create_subscription_for_scope(user_id=int(current_user.id), company_id=cid)
    tier = sub.effective_tier() if hasattr(sub, "effective_tier") else None
    stripe_ready = _stripe_configured()
    usage = _compute_usage_for_manage()

    return render_template(
        "billing/manage.html",
        tier=tier,
        sub=sub,
        stripe_ready=stripe_ready,
        usage=usage,
        free_days=_get_free_days(),
        pro_trial_days=_get_pro_trial_days(),
    )


# -------------------------
# Checkout / Portal (Stripe)
# -------------------------
@bp.post("/checkout/pro")
@login_required
def checkout_pro():
    """
    پرداخت قدیمی را نگه داشتیم؛ به عنوان silver (نامحدود) لحاظ می‌شود.
    در سناریوی multi-tenant، این پرداخت برای شرکت انجام می‌شود.
    """
    if stripe is None:
        flash("پرداخت آنلاین فعال نیست (stripe نصب نشده). لطفاً برای خرید پلن تماس بگیرید.", "warning")
        return redirect(url_for("billing.pricing", next=_clean_next_url()))

    if not _stripe_configured():
        flash("پرداخت آنلاین هنوز تنظیم نشده است. لطفاً برای خرید پلن تماس بگیرید.", "warning")
        return redirect(url_for("billing.pricing", next=_clean_next_url()))

    _stripe_init()

    price_id = os.getenv("STRIPE_PRICE_ID_PRO")
    if not price_id:
        abort(500, description="STRIPE_PRICE_ID_PRO is not set")

    cid = _current_company_id()
    sub = _get_or_create_subscription_for_scope(user_id=int(current_user.id), company_id=cid)
    next_url = _clean_next_url()

    success_url = url_for(
        "billing.success",
        _external=True,
        session_id="{CHECKOUT_SESSION_ID}",
        next=next_url or None,
    )
    cancel_url = url_for("billing.cancel", _external=True)

    trial_days = _get_pro_trial_days()
    subscription_data: dict = {}
    if trial_days > 0 and not getattr(sub, "stripe_subscription_id", None):
        subscription_data["trial_period_days"] = trial_days

    # company-based: client_reference_id = company_id
    client_ref = str(cid) if _subscription_is_company_based() and cid is not None else str(current_user.id)

    session_obj = stripe.checkout.Session.create(
        mode="subscription",
        customer=getattr(sub, "stripe_customer_id", None) or None,
        customer_email=None if getattr(sub, "stripe_customer_id", None) else getattr(current_user, "email", None),
        client_reference_id=client_ref,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        automatic_tax={"enabled": False},
        subscription_data=subscription_data or None,
        metadata={
            "user_id": str(current_user.id),
            "company_id": str(cid) if cid is not None else "",
        },
    )

    return redirect(session_obj.url, code=303)


@bp.get("/success")
@login_required
def success():
    next_url = request.args.get("next") or ""
    if next_url and not _is_safe_next_url(next_url):
        next_url = ""

    session_id = request.args.get("session_id") or ""
    if session_id:
        _try_sync_from_checkout_session(session_id)

    return render_template("billing/success.html", next=next_url)


@bp.get("/cancel")
@login_required
def cancel():
    return render_template("billing/cancel.html")


@bp.post("/portal")
@login_required
def portal():
    if stripe is None:
        flash("پرداخت آنلاین فعال نیست (stripe نصب نشده).", "danger")
        return redirect(url_for("billing.pricing"))

    if not os.getenv("STRIPE_SECRET_KEY"):
        flash("Stripe هنوز تنظیم نشده است.", "danger")
        return redirect(url_for("billing.pricing"))

    _stripe_init()

    cid = _current_company_id()
    sub = _get_or_create_subscription_for_scope(user_id=int(current_user.id), company_id=cid)
    if not getattr(sub, "stripe_customer_id", None):
        flash("برای مدیریت اشتراک، ابتدا پلن را خریداری کنید.", "warning")
        return redirect(url_for("billing.pricing"))

    return_url = url_for("billing.manage", _external=True)
    session_obj = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=return_url,
    )
    return redirect(session_obj.url, code=303)


# -------------------------
# Owner Admin: Manual plan control
# -------------------------
def _set_plan_for_scope(*, user_id: int, company_id: Optional[int], plan: str) -> None:
    """
    ست کردن پلن‌های جدید: free/bronze/silver/gold
    - پلن‌های پولی: اعتبار ۱ ساله
    - free: دوره رایگان (FREE_DAYS)
    """
    sub = _get_or_create_subscription_for_scope(user_id=int(user_id), company_id=company_id)

    prev_plan = getattr(sub, "plan", None)
    prev_end = getattr(sub, "current_period_end", None)

    sub.status = "active"
    sub.cancel_at_period_end = False

    # حالت دستی: Stripe را خنثی کنیم
    if hasattr(sub, "stripe_subscription_id"):
        sub.stripe_subscription_id = None
    if hasattr(sub, "stripe_customer_id"):
        sub.stripe_customer_id = None

    if plan == "free":
        sub.current_period_end = None
        sub.start_free_period(days=_get_free_days())
    else:
        sub.plan = plan
        sub.current_period_end = datetime.utcnow() + timedelta(days=365)

    # billing_user_id
    if _subscription_is_company_based() and hasattr(sub, "billing_user_id"):
        try:
            sub.billing_user_id = int(user_id)
        except Exception:
            pass

    db.session.commit()

    _maybe_send_plan_activated_sms(
        user_id=int(user_id),
        previous_plan=prev_plan,
        previous_end=prev_end,
        new_plan=str(getattr(sub, "plan", "") or ""),
        new_end=getattr(sub, "current_period_end", None),
    )


@bp.post("/admin/subscription/<int:user_id>/plan/set")
@login_required
@owner_required
def admin_set_plan(user_id: int):
    """
    برای سازگاری با UI قبلی، هنوز user_id می‌گیرد؛
    ولی اگر سیستم company-based باشد، پلن را برای company آن کاربر ست می‌کند.
    """
    user = db.session.get(User, int(user_id))
    if not user:
        abort(404)

    plan = (request.form.get("plan") or "").strip().lower()
    if plan not in {"free", "bronze", "silver", "gold"}:
        abort(400, description="Invalid plan")

    cid = getattr(user, "company_id", None)
    if _subscription_is_company_based() and cid is None:
        abort(400, description="Target user has no company_id; cannot set company subscription")

    _set_plan_for_scope(user_id=int(user.id), company_id=int(cid) if cid is not None else None, plan=plan)
    flash(f"پلن با موفقیت به {plan.upper()} تغییر کرد.", "success")
    return redirect(request.referrer or url_for("billing.manage"))


# -------------------------
# Webhook (CSRF Exempt)
# -------------------------
@bp.post("/webhook")
@csrf_exempt
def webhook():
    if stripe is None:
        abort(500, description="stripe package is not installed. Run: pip install stripe")

    _stripe_init()

    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        abort(500, description="STRIPE_WEBHOOK_SECRET is not set")

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=webhook_secret)
    except Exception:
        return ("bad signature", 400)

    etype = event.get("type", "")
    data_obj = (event.get("data") or {}).get("object") or {}
    data = _stripe_to_dict(data_obj)

    # checkout.session.completed
    if etype == "checkout.session.completed":
        try:
            stripe_subscription_id = data.get("subscription")
            meta = data.get("metadata") or {}

            uid_raw = meta.get("user_id") or data.get("client_reference_id")
            cid_raw = meta.get("company_id") or (data.get("client_reference_id") if _subscription_is_company_based() else "")

            uid = int(uid_raw) if uid_raw else None
            cid = int(cid_raw) if cid_raw else None

            if uid is not None and stripe_subscription_id:
                sub_obj = stripe.Subscription.retrieve(str(stripe_subscription_id))
                _update_subscription_from_stripe(sub_obj, user_id=uid, company_id=cid)
        except Exception:
            current_app.logger.exception("Failed handling checkout.session.completed webhook")

    # customer.subscription.updated / deleted
    if etype in {"customer.subscription.updated", "customer.subscription.deleted"}:
        try:
            sid = data.get("id")
            if sid:
                sub = Subscription.query.filter_by(stripe_subscription_id=str(sid)).one_or_none()
                if sub:
                    uid = int(getattr(sub, "billing_user_id", None) or 0) or int(current_app.config.get("OWNER_USER_ID", 1))
                    cid = getattr(sub, "company_id", None) if _subscription_is_company_based() else None
                    _update_subscription_from_stripe(data_obj, user_id=uid, company_id=int(cid) if cid is not None else None)
        except Exception:
            current_app.logger.exception("Failed handling subscription update/delete webhook")

    return ("ok", 200)