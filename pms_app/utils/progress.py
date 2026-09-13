# Path: pms_app/utils/progress.py
"""
Progress summary helpers for project / contract cards.
- Overall weighted progress (by BAC)
- Breakdown by discipline
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence


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
    p = _f(getattr(item, "actual_progress_percentage", None))
    return max(0.0, min(100.0, p))


def _item_discipline(item) -> str:
    d = (
        getattr(item, "discipline", None)
        or getattr(item, "l4_discipline", None)
        or getattr(item, "phase", None)
        or getattr(item, "l3_phase", None)
    )
    d = (str(d).strip() if d else "") or "عمومی"
    return d


def summarize_items(items: Sequence) -> Dict[str, Any]:
    """
    Return:
      overall_pct, item_count, bac_total, ac_total, ev_total,
      disciplines: [{name, pct, weight, item_count}, ...]  (top by weight)
    """
    items = list(items or [])
    if not items:
        return {
            "overall_pct": 0.0,
            "item_count": 0,
            "bac_total": 0.0,
            "ac_total": 0.0,
            "ev_total": 0.0,
            "disciplines": [],
            "phases": [],
        }

    bac_total = 0.0
    ev_total = 0.0
    ac_total = 0.0

    # discipline -> {bac, ev, count}
    disc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"bac": 0.0, "ev": 0.0, "count": 0})
    from pms_app.utils.epc import classify_epc_phase, PHASE_LABELS

    phase_acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"bac": 0.0, "ev": 0.0, "count": 0})

    for it in items:
        bac = _item_bac(it)
        pct = _item_progress(it)
        ev = bac * pct / 100.0
        ac = _f(getattr(it, "actual_cost", None))

        bac_total += bac
        ev_total += ev
        ac_total += ac

        name = _item_discipline(it)
        disc[name]["bac"] += bac
        disc[name]["ev"] += ev
        disc[name]["count"] += 1

        phase = classify_epc_phase(it)
        phase_acc[phase]["bac"] += bac
        phase_acc[phase]["ev"] += ev
        phase_acc[phase]["count"] += 1

    if bac_total > 0:
        overall = round(ev_total / bac_total * 100.0, 1)
    else:
        # fallback: simple average of item progress
        overall = round(
            sum(_item_progress(it) for it in items) / len(items), 1
        ) if items else 0.0

    disciplines: List[Dict[str, Any]] = []
    for name, data in disc.items():
        if data["bac"] > 0:
            pct = round(data["ev"] / data["bac"] * 100.0, 1)
            weight = data["bac"]
        else:
            pct = 0.0
            weight = 0.0
        disciplines.append({
            "name": name,
            "pct": pct,
            "weight": weight,
            "item_count": int(data["count"]),
        })

    # sort by weight desc, then name
    disciplines.sort(key=lambda x: (-x["weight"], x["name"]))

    phases = []
    for key in ("engineering", "procurement", "construction", "other"):
        data = phase_acc.get(key) or {"bac": 0.0, "ev": 0.0, "count": 0}
        if data["bac"] > 0:
            ppct = round(data["ev"] / data["bac"] * 100.0, 1)
        else:
            ppct = 0.0
        phases.append(
            {
                "key": key,
                "name": PHASE_LABELS.get(key, key),
                "pct": ppct,
                "item_count": int(data["count"]),
            }
        )

    return {
        "overall_pct": overall,
        "item_count": len(items),
        "bac_total": bac_total,
        "ac_total": ac_total,
        "ev_total": ev_total,
        "disciplines": disciplines[:6],  # top 6 for cards
        "phases": phases,
    }


def project_progress(project) -> Dict[str, Any]:
    items = []
    contract_count = 0
    for c in getattr(project, "contracts", []) or []:
        contract_count += 1
        items.extend(list(getattr(c, "items", []) or []))
    summary = summarize_items(items)
    summary["contract_count"] = contract_count
    return summary


def contract_progress(contract) -> Dict[str, Any]:
    items = list(getattr(contract, "items", []) or [])
    return summarize_items(items)
