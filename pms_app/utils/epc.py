# Path: pms_app/utils/epc.py
"""
EPC project-controls helpers.

Classify WBS/CBS items into Engineering / Procurement / Construction
and assemble a control-room snapshot (progress, lookahead, delays, HSE, concerns).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

ENGINEERING_KEYS = (
    "eng", "engineer", "design", "drawing", "ifc", "ifd", "ifa", "document",
    "pid", "p&id", "isometric", "spec", "مهندسی", "طراحی", "نقشه", "مدرک",
)
PROCUREMENT_KEYS = (
    "proc", "purchas", "material", "vendor", "mr ", "m.r", "po ", "expedit",
    "supply", "تدارک", "خرید", "سفارش", "مصالح", "تجهیزات خرید", "vendor",
)
CONSTRUCTION_KEYS = (
    "const", "install", "civil", "mech", "elec", "piping", "welding", "erect",
    "commission", "precom", "site", "excav", "concrete", "steel",
    "اجرا", "نصب", "ساخت", "عمران", "سیویل", "مکانیک", "برق", "پایپینگ",
    "بتن", "جوش", "راه‌اندازی", "کارگاه",
)

PHASE_LABELS = {
    "engineering": "مهندسی (E)",
    "procurement": "تدارکات (P)",
    "construction": "اجرا (C)",
    "other": "سایر / مشترک",
}

PHASE_HINTS = {
    "engineering": ENGINEERING_KEYS,
    "procurement": PROCUREMENT_KEYS,
    "construction": CONSTRUCTION_KEYS,
}


def _blob(item) -> str:
    parts = [
        getattr(item, "l3_phase", None),
        getattr(item, "phase", None),
        getattr(item, "discipline", None),
        getattr(item, "l4_discipline", None),
        getattr(item, "work_package", None),
        getattr(item, "l8_work_package", None),
        getattr(item, "cost_category", None),
        getattr(item, "title", None),
        getattr(item, "wbs_code", None),
        getattr(item, "cbs_code", None),
        getattr(item, "l9_activity_name", None),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def classify_epc_phase(item, explicit: Optional[str] = None) -> str:
    raw = (explicit or getattr(item, "epc_phase", None) or "").strip().lower()
    aliases = {
        "e": "engineering",
        "eng": "engineering",
        "engineering": "engineering",
        "مهندسی": "engineering",
        "p": "procurement",
        "proc": "procurement",
        "procurement": "procurement",
        "تدارکات": "procurement",
        "خرید": "procurement",
        "c": "construction",
        "const": "construction",
        "construction": "construction",
        "اجرا": "construction",
        "ساخت": "construction",
    }
    if raw in aliases:
        return aliases[raw]
    text = _blob(item)
    scores = {phase: sum(1 for k in keys if k in text) for phase, keys in PHASE_HINTS.items()}
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return "other"
    return best


def _f(v, default=0.0) -> float:
    if v is None:
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _item_bac(item) -> float:
    if getattr(item, "adjusted_amount", None) is not None:
        return _f(item.adjusted_amount)
    return _f(getattr(item, "original_amount", None))


def _item_progress(item) -> float:
    return max(0.0, min(100.0, _f(getattr(item, "actual_progress_percentage", None))))


def _collect_items(project) -> List:
    items = []
    for contract in getattr(project, "contracts", []) or []:
        items.extend(list(getattr(contract, "items", []) or []))
    return items


def summarize_epc_phases(items: Sequence) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, float]] = {
        k: {"bac": 0.0, "ev": 0.0, "ac": 0.0, "count": 0, "done": 0}
        for k in ("engineering", "procurement", "construction", "other")
    }
    for it in items:
        phase = classify_epc_phase(it)
        bac = _item_bac(it)
        pct = _item_progress(it)
        buckets[phase]["bac"] += bac
        buckets[phase]["ev"] += bac * pct / 100.0
        buckets[phase]["ac"] += _f(getattr(it, "actual_cost", None))
        buckets[phase]["count"] += 1
        if pct >= 99.5:
            buckets[phase]["done"] += 1

    out = []
    for key in ("engineering", "procurement", "construction", "other"):
        data = buckets[key]
        if data["bac"] > 0:
            pct = round(data["ev"] / data["bac"] * 100.0, 1)
        elif data["count"]:
            pct = 0.0
        else:
            pct = 0.0
        out.append(
            {
                "key": key,
                "label": PHASE_LABELS[key],
                "pct": pct,
                "bac": data["bac"],
                "ev": data["ev"],
                "ac": data["ac"],
                "item_count": int(data["count"]),
                "done_count": int(data["done"]),
            }
        )
    return {"phases": out, "by_key": {p["key"]: p for p in out}}


def project_epc_controls(project, *, as_of: Optional[date] = None) -> Dict[str, Any]:
    """Control-room payload for an EPC project."""
    as_of = as_of or date.today()
    items = _collect_items(project)
    phases = summarize_epc_phases(items)

    lookahead_end = as_of + timedelta(days=14)
    lookahead = []
    delayed = []
    milestones = []
    for it in items:
        pct = _item_progress(it)
        start = getattr(it, "baseline_start_date", None) or getattr(it, "actual_start_date", None)
        finish = getattr(it, "baseline_end_date", None) or getattr(it, "forecast_finish_date", None)
        if getattr(it, "is_milestone", False):
            milestones.append(it)
        if pct < 99.5 and finish and finish < as_of and getattr(it, "status", "open") not in ("closed", "completed", "cancelled"):
            delayed.append(
                {
                    "id": it.id,
                    "title": it.title,
                    "wbs": it.wbs_code or it.pms_item_number or "",
                    "phase": classify_epc_phase(it),
                    "pct": pct,
                    "finish": finish,
                    "days_late": (as_of - finish).days,
                    "discipline": it.discipline or it.l4_discipline or "",
                }
            )
        window_hit = False
        if start and as_of <= start <= lookahead_end and pct < 99.5:
            window_hit = True
        if finish and as_of <= finish <= lookahead_end and pct < 99.5:
            window_hit = True
        if window_hit:
            lookahead.append(
                {
                    "id": it.id,
                    "title": it.title,
                    "wbs": it.wbs_code or it.pms_item_number or "",
                    "phase": classify_epc_phase(it),
                    "pct": pct,
                    "start": start,
                    "finish": finish,
                    "discipline": it.discipline or it.l4_discipline or "",
                }
            )

    delayed.sort(key=lambda x: -x["days_late"])
    lookahead.sort(key=lambda x: (x["start"] or x["finish"] or as_of, x["title"]))

    from pms_app.models.daily_report import DailyReport
    from pms_app.models.concern import Concern

    recent_reports = (
        DailyReport.query.filter_by(project_id=project.id)
        .order_by(DailyReport.report_date.desc())
        .limit(14)
        .all()
    )
    hse = {
        "near_miss": 0,
        "incidents": 0,
        "manpower_avg": 0,
        "lost_hours": 0.0,
        "days": len(recent_reports),
    }
    manpower_series = []
    for r in reversed(recent_reports):
        hse["near_miss"] += int(r.near_miss_count or 0)
        if r.hse_incidents and str(r.hse_incidents).strip():
            hse["incidents"] += 1
        hse["lost_hours"] += _f(getattr(r, "lost_time_hours", None))
        manpower_series.append({"date": r.report_date, "count": int(r.manpower_total or 0)})
    if recent_reports:
        hse["manpower_avg"] = round(
            sum(int(r.manpower_total or 0) for r in recent_reports) / len(recent_reports)
        )

    open_concerns = (
        Concern.query.filter_by(project_id=project.id)
        .filter(Concern.status.in_(("open", "acknowledged", "in_progress", "escalated")))
        .all()
    )
    by_cat: Dict[str, int] = defaultdict(int)
    critical = 0
    for c in open_concerns:
        by_cat[c.category or "other"] += 1
        if c.priority == "critical":
            critical += 1

    from pms_app.utils.progress import summarize_items
    from pms_app.utils.evm import project_evm

    progress = summarize_items(items)
    evm = project_evm(project, as_of=as_of).as_dict()

    return {
        "as_of": as_of,
        "item_count": len(items),
        "phases": phases["phases"],
        "phase_map": phases["by_key"],
        "lookahead": lookahead[:20],
        "delayed": delayed[:20],
        "delayed_count": len(delayed),
        "milestone_count": len(milestones),
        "hse": hse,
        "manpower_series": manpower_series,
        "concerns_open": len(open_concerns),
        "concerns_critical": critical,
        "concerns_by_category": dict(by_cat),
        "progress": progress,
        "evm": evm,
        "recent_reports": recent_reports[:8],
    }
