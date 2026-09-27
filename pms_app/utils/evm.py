# Path: pms_app/utils/evm.py
"""
Earned Value Management (EVM) + S-Curve.
PV priority: planned_progress_percentage → linear baseline dates.
BAC: adjusted_amount → original_amount → qty×unit_price (via item.bac).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Sequence, Union

Number = Union[int, float, Decimal, None]


def _d(value: Number, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _q(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _safe_div(numerator: Decimal, denominator: Decimal) -> Optional[Decimal]:
    if denominator == 0:
        return None
    return numerator / denominator


@dataclass
class EVMResult:
    bac: Decimal = Decimal("0")
    ev: Decimal = Decimal("0")
    ac: Decimal = Decimal("0")
    pv: Optional[Decimal] = None
    percent_complete: Decimal = Decimal("0")
    cv: Optional[Decimal] = None
    sv: Optional[Decimal] = None
    cpi: Optional[Decimal] = None
    spi: Optional[Decimal] = None
    eac: Optional[Decimal] = None
    etc: Optional[Decimal] = None
    vac: Optional[Decimal] = None
    tcpi: Optional[Decimal] = None

    def as_dict(self) -> dict:
        def fmt(v: Optional[Decimal]):
            if v is None:
                return None
            return float(_q(v))

        return {
            "bac": fmt(self.bac),
            "ev": fmt(self.ev),
            "ac": fmt(self.ac),
            "pv": fmt(self.pv),
            "percent_complete": float(_q(self.percent_complete, "0.01")),
            "cv": fmt(self.cv),
            "sv": fmt(self.sv),
            "cpi": float(_q(self.cpi, "0.0001")) if self.cpi is not None else None,
            "spi": float(_q(self.spi, "0.0001")) if self.spi is not None else None,
            "eac": fmt(self.eac),
            "etc": fmt(self.etc),
            "vac": fmt(self.vac),
            "tcpi": float(_q(self.tcpi, "0.0001")) if self.tcpi is not None else None,
        }


def calculate_item_evm(
    *,
    bac: Number,
    progress_percent: Number,
    actual_cost: Number = None,
    planned_progress_percent: Number = None,
    baseline_start: Optional[date] = None,
    baseline_end: Optional[date] = None,
    as_of: Optional[date] = None,
    weight: Number = None,
) -> EVMResult:
    bac_d = _d(bac)
    progress = max(Decimal("0"), min(_d(progress_percent), Decimal("100")))
    ac_d = _d(actual_cost)

    ev = _q(bac_d * (progress / Decimal("100")))

    # PV: prefer explicit planned %; else linear from baseline dates
    pv = None
    as_of = as_of or date.today()
    if planned_progress_percent is not None:
        planned = max(Decimal("0"), min(_d(planned_progress_percent), Decimal("100")))
        pv = _q(bac_d * (planned / Decimal("100")))
    elif baseline_start and baseline_end and baseline_end > baseline_start:
        total_days = (baseline_end - baseline_start).days
        if total_days > 0:
            elapsed = max(0, min((as_of - baseline_start).days, total_days))
            planned_pct = Decimal(elapsed) / Decimal(total_days)
            pv = _q(bac_d * planned_pct)

    cv = _q(ev - ac_d)
    sv = _q(ev - pv) if pv is not None else None

    cpi = _safe_div(ev, ac_d) if ac_d > 0 else (Decimal("1") if ev == 0 else None)
    spi = _safe_div(ev, pv) if pv and pv > 0 else None

    eac = None
    if cpi and cpi > 0:
        eac = _q(bac_d / cpi)
    elif ac_d > 0 and progress > 0:
        eac = _q(ac_d + (bac_d - ev))

    etc = _q(eac - ac_d) if eac is not None else None
    vac = _q(bac_d - eac) if eac is not None else None

    remaining_work = bac_d - ev
    remaining_funds = bac_d - ac_d
    tcpi = _safe_div(remaining_work, remaining_funds) if remaining_funds != 0 else None

    return EVMResult(
        bac=bac_d,
        ev=ev,
        ac=ac_d,
        pv=pv,
        percent_complete=progress,
        cv=cv,
        sv=sv,
        cpi=_q(cpi, "0.0001") if cpi is not None else None,
        spi=_q(spi, "0.0001") if spi is not None else None,
        eac=eac,
        etc=etc,
        vac=vac,
        tcpi=_q(tcpi, "0.0001") if tcpi is not None else None,
    )


def aggregate_evm(results: Sequence[EVMResult]) -> EVMResult:
    if not results:
        return EVMResult()

    total_bac = sum((r.bac for r in results), Decimal("0"))
    total_ev = sum((r.ev for r in results), Decimal("0"))
    total_ac = sum((r.ac for r in results), Decimal("0"))

    total_pv = None
    pvs = [r.pv for r in results if r.pv is not None]
    if pvs:
        total_pv = sum(pvs, Decimal("0"))

    percent = Decimal("0")
    if total_bac > 0:
        percent = _q((total_ev / total_bac) * Decimal("100"), "0.01")

    cv = _q(total_ev - total_ac)
    sv = _q(total_ev - total_pv) if total_pv is not None else None

    cpi = _safe_div(total_ev, total_ac) if total_ac > 0 else None
    spi = _safe_div(total_ev, total_pv) if total_pv and total_pv > 0 else None

    eac = None
    if cpi and cpi > 0:
        eac = _q(total_bac / cpi)
    elif total_ac > 0 and percent > 0:
        eac = _q(total_ac + (total_bac - total_ev))

    etc = _q(eac - total_ac) if eac is not None else None
    vac = _q(total_bac - eac) if eac is not None else None

    remaining_work = total_bac - total_ev
    remaining_funds = total_bac - total_ac
    tcpi = _safe_div(remaining_work, remaining_funds) if remaining_funds != 0 else None

    return EVMResult(
        bac=total_bac,
        ev=total_ev,
        ac=total_ac,
        pv=total_pv,
        percent_complete=percent,
        cv=cv,
        sv=sv,
        cpi=_q(cpi, "0.0001") if cpi is not None else None,
        spi=_q(spi, "0.0001") if spi is not None else None,
        eac=eac,
        etc=etc,
        vac=vac,
        tcpi=_q(tcpi, "0.0001") if tcpi is not None else None,
    )


def item_evm(item, as_of: Optional[date] = None) -> EVMResult:
    # Prefer model bac property (handles qty×price)
    bac = getattr(item, "bac", None)
    if bac is None:
        bac = item.adjusted_amount if item.adjusted_amount is not None else item.original_amount

    progress = item.actual_progress_percentage or 0
    planned = getattr(item, "planned_progress_percentage", None)
    ac = item.actual_cost

    return calculate_item_evm(
        bac=bac,
        progress_percent=progress,
        actual_cost=ac,
        planned_progress_percent=planned,
        baseline_start=item.baseline_start_date,
        baseline_end=item.baseline_end_date,
        as_of=as_of,
        weight=item.weight_factor,
    )


def contract_evm(contract, as_of: Optional[date] = None) -> EVMResult:
    items = list(contract.items) if hasattr(contract, "items") else []
    results = [item_evm(it, as_of=as_of) for it in items]
    return aggregate_evm(results)


def project_evm(project, as_of: Optional[date] = None) -> EVMResult:
    results = []
    for contract in getattr(project, "contracts", []):
        results.append(contract_evm(contract, as_of=as_of))
    return aggregate_evm(results)


@dataclass
class SCurveData:
    labels: List[str] = field(default_factory=list)
    pv: List[Optional[float]] = field(default_factory=list)
    ev: List[float] = field(default_factory=list)
    baseline_valid: bool = False
    ac: List[float] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "labels": self.labels,
            "pv": self.pv,
            "ev": self.ev,
            "baseline_valid": self.baseline_valid,
            "ac": self.ac,
            "dates": self.dates,
        }


def _month_end(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(
        d.day,
        [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
        ][month - 1],
    )
    return date(year, month, day)


def _linear_cum(bac: Decimal, start: Optional[date], end: Optional[date], as_of: date) -> Decimal:
    if bac <= 0 or not start or not end or end <= start:
        return Decimal("0")
    if as_of <= start:
        return Decimal("0")
    if as_of >= end:
        return bac
    total_days = (end - start).days
    elapsed = (as_of - start).days
    return _q(bac * Decimal(elapsed) / Decimal(total_days))


def _jalali_label(d: date) -> str:
    try:
        from pms_app.utils.jalali import format_jalali_month
        return format_jalali_month(d) or d.strftime("%Y-%m")
    except Exception:
        return d.strftime("%Y-%m")


def generate_s_curve(
    project,
    *,
    months: int = 12,
    as_of: Optional[date] = None,
    jalali_labels: bool = True,
) -> SCurveData:
    as_of = as_of or getattr(project, "data_date", None) or date.today()

    items = []
    for contract in getattr(project, "contracts", []):
        items.extend(list(getattr(contract, "items", [])))

    project_baseline_start = getattr(project, "baseline_start_date", None)
    project_baseline_finish = getattr(project, "baseline_finish_date", None)

    starts = []
    ends = []
    if project.start_date:
        starts.append(project.start_date)
    if project.finish_date:
        ends.append(project.finish_date)
    if getattr(project, "baseline_start_date", None):
        starts.append(project.baseline_start_date)
    if getattr(project, "baseline_finish_date", None):
        ends.append(project.baseline_finish_date)

    for it in items:
        if it.baseline_start_date:
            starts.append(it.baseline_start_date)
        if it.baseline_end_date:
            ends.append(it.baseline_end_date)
        if it.actual_start_date:
            starts.append(it.actual_start_date)

    if not starts:
        starts.append(as_of.replace(day=1))
    if not ends:
        ends.append(as_of)

    start_date = min(starts)
    end_date = max(ends)
    if end_date < as_of:
        end_date = as_of

    points: List[date] = []
    cursor = date(start_date.year, start_date.month, 1)
    while cursor <= end_date:
        points.append(_month_end(cursor))
        cursor = _add_months(cursor, 1)
        if len(points) > 60:
            break

    if not points:
        points = [as_of]

    item_data = []
    baseline_valid = bool(project_baseline_start and project_baseline_end and project_baseline_end > project_baseline_start)
    for it in items:
        bac_val = getattr(it, "bac", None)
        bac = _d(bac_val if bac_val is not None else (
            it.adjusted_amount if it.adjusted_amount is not None else it.original_amount
        ))
        progress = max(Decimal("0"), min(_d(it.actual_progress_percentage), Decimal("100")))
        ac = _d(it.actual_cost)
        ev_final = _q(bac * progress / Decimal("100"))

        # Planned-value curves must come from an approved baseline, never from
        # current/forecast project dates. An item may inherit the project baseline.
        b_start = it.baseline_start_date or project_baseline_start
        b_end = it.baseline_end_date or project_baseline_finish
        item_baseline_valid = bool(b_start and b_end and b_end > b_start)
        baseline_valid = baseline_valid and item_baseline_valid
        a_start = it.actual_start_date or b_start or start_date

        item_data.append({
            "bac": bac,
            "ev_final": ev_final,
            "ac_final": ac,
            "b_start": b_start,
            "b_end": b_end,
            "a_start": a_start,
        })

    labels = []
    pv_series: List[Optional[float]] = []
    ev_series = []
    ac_series = []
    date_strs = []

    for pt in points:
        cum_pv = Decimal("0")
        cum_ev = Decimal("0")
        cum_ac = Decimal("0")

        for d in item_data:
            cum_pv += _linear_cum(d["bac"], d["b_start"], d["b_end"], pt)
            ref_date = min(pt, as_of)
            cum_ev += _linear_cum(d["ev_final"], d["a_start"], as_of, ref_date)
            cum_ac += _linear_cum(d["ac_final"], d["a_start"], as_of, ref_date)

        labels.append(_jalali_label(pt) if jalali_labels else pt.strftime("%Y-%m"))
        date_strs.append(pt.isoformat())
        pv_series.append(float(_q(cum_pv)) if baseline_valid else None)
        ev_series.append(float(_q(cum_ev)))
        ac_series.append(float(_q(cum_ac)))

    return SCurveData(
        labels=labels,
        pv=pv_series,
        ev=ev_series,
        ac=ac_series,
        dates=date_strs,
        baseline_valid=baseline_valid,
    )


def project_s_curve(project, **kwargs) -> dict:
    return generate_s_curve(project, **kwargs).as_dict()
