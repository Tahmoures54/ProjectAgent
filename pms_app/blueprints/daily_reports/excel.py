# Path: pms_app/blueprints/daily_reports/excel.py
"""Excel template, import, and export for daily site reports."""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from pms_app.extensions import db
from pms_app.models.daily_report import DailyReport
from pms_app.models.item import ContractItem
from pms_app.utils.excel_io import (
    autosize,
    cell,
    header_index,
    iter_data_rows,
    parse_excel_date,
    require_openpyxl,
    style_header_row,
    to_float,
    to_int,
    workbook_to_bytes,
)
from pms_app.utils.jalali import format_jalali

DAILY_ALIASES = {
    "report_date": ("date", "report_date", "تاریخ", "تاریخگزارش", "روز"),
    "epc_phase": ("epc_phase", "phase", "فاز", "فازepc", "epc"),
    "shift": ("shift", "شیفت"),
    "work_area": ("work_area", "area", "ناحیه", "محل", "جبهه", "جبههکار"),
    "weather": ("weather", "هوا", "وضعیتهوا"),
    "temperature_min": ("temperature_min", "tmin", "دمایحداقل", "حداقلدما", "mintemp"),
    "temperature_max": ("temperature_max", "tmax", "دمایحداکثر", "حداکثردما", "maxtemp"),
    "manpower_total": ("manpower_total", "manpower", "نیرو", "نیرویانسانی", "تعدادنفرات"),
    "work_performed": ("work_performed", "work", "شرحکار", "کارهایانجامشده", "فعالیت"),
    "issues_delays": ("issues_delays", "issues", "مشکلات", "تاخیر", "تأخیر", "موانع"),
    "hse_incidents": ("hse_incidents", "incidents", "حوادث", "حادثه"),
    "hse_observations": ("hse_observations", "observations", "مشاهداتایمنی", "hse"),
    "near_miss_count": ("near_miss_count", "nearmiss", "نییرمیس", "تعدادnearmiss"),
    "visitors_meetings": ("visitors_meetings", "visitors", "بازدید", "جلسات"),
    "notes": ("notes", "یادداشت", "توضیحات"),
    "lost_time_hours": ("lost_time_hours", "losthours", "ساعتتوقف", "توقفکار"),
}

MANPOWER_ALIASES = {
    "report_date": ("date", "report_date", "تاریخ"),
    "role": ("role", "نقش", "شغل", "رسته"),
    "count": ("count", "تعداد", "نفر"),
}

EQUIPMENT_ALIASES = {
    "report_date": ("date", "report_date", "تاریخ"),
    "name": ("name", "نام", "ماشین", "تجهیز"),
    "count": ("count", "تعداد"),
    "hours": ("hours", "ساعت", "ساعتکار"),
}

PROGRESS_ALIASES = {
    "report_date": ("date", "report_date", "تاریخ"),
    "contract_item_id": ("contract_item_id", "item_id", "id", "شناسه", "شناسهآیتم"),
    "wbs_code": ("wbs_code", "wbs", "کدwbs", "کدآیتم", "کدفالیت"),
    "progress_percent": ("progress_percent", "progress", "درصد", "درصدپیشرفت"),
    "quantity_done": ("quantity_done", "qty", "مقدار", "مقدارانجامشده"),
    "notes": ("notes", "یادداشت", "شرح"),
}

MATERIALS_ALIASES = {
    "report_date": ("date", "report_date", "تاریخ"),
    "name": ("name", "نام", "مصالح", "کالا"),
    "qty": ("qty", "quantity", "مقدار", "تعداد"),
    "unit": ("unit", "واحد"),
    "vendor": ("vendor", "فروشنده", "تامینکننده", "تأمین‌کننده"),
}

WEATHER_MAP = {
    "آفتابی": "sunny",
    "sunny": "sunny",
    "نیمه ابری": "partly_cloudy",
    "نیمه‌ابری": "partly_cloudy",
    "partly_cloudy": "partly_cloudy",
    "ابری": "cloudy",
    "cloudy": "cloudy",
    "بارانی": "rainy",
    "rainy": "rainy",
    "طوفانی": "stormy",
    "stormy": "stormy",
    "برفی": "snowy",
    "snowy": "snowy",
    "مه": "foggy",
    "foggy": "foggy",
    "باد شدید": "windy",
    "بادشدید": "windy",
    "windy": "windy",
}

PHASE_MAP = {
    "e": "engineering",
    "مهندسی": "engineering",
    "engineering": "engineering",
    "p": "procurement",
    "تدارکات": "procurement",
    "خرید": "procurement",
    "procurement": "procurement",
    "c": "construction",
    "اجرا": "construction",
    "ساخت": "construction",
    "construction": "construction",
    "ترکیبی": "mixed",
    "mixed": "mixed",
    "epc": "mixed",
}

SHIFT_MAP = {
    "روز": "day",
    "روزکار": "day",
    "day": "day",
    "شب": "night",
    "شبکار": "night",
    "night": "night",
    "کامل": "full",
    "تماموقت": "full",
    "full": "full",
}


def _map_choice(value, mapping: Dict[str, str]) -> Optional[str]:
    if value is None or value == "":
        return None
    key = str(value).strip().lower().replace(" ", "").replace("\u200c", "")
    for k, v in mapping.items():
        if key == k.lower().replace(" ", "").replace("\u200c", ""):
            return v
    return str(value).strip()[:40]


def build_template_workbook(project, items: Optional[List[ContractItem]] = None):
    ox = require_openpyxl()
    if not ox:
        raise RuntimeError("openpyxl نصب نیست.")
    Workbook = ox["Workbook"]
    Font = ox["Font"]
    Alignment = ox["Alignment"]
    PatternFill = ox["PatternFill"]

    wb = Workbook()

    guide = wb.active
    guide.title = "راهنما"
    guide.sheet_view.rightToLeft = True
    guide["A1"] = "قالب گزارش روزانه کارگاه — Project Agent"
    guide["A1"].font = Font(bold=True, size=16, color="0E7F9B")
    guide.merge_cells("A1:D1")
    lines = [
        f"پروژه: {project.project_name} ({project.project_code})",
        "هر ردیف در برگه «گزارش روزانه» یک روز است. تاریخ را خورشیدی (1403/06/20) یا میلادی (2026-09-13) بنویسید.",
        "برگه‌های نیروی انسانی، ماشین‌آلات، پیشرفت و مصالح اختیاری‌اند و با همان تاریخ به گزارش وصل می‌شوند.",
        "اگر برای یک تاریخ چند ردیف نیروی انسانی بنویسید، همه در همان گزارش ذخیره می‌شوند.",
        "ستون «کد WBS» در پیشرفت می‌تواند شناسه آیتم، کد WBS یا شماره PMS باشد.",
        "پس از ورود، گزارش‌ها به‌صورت پیش‌نویس ذخیره می‌شوند تا بررسی و ارسال کنید.",
        "برگه نمونه را پاک نکنید؛ ردیف اول هدر است و نباید حذف شود.",
    ]
    for i, line in enumerate(lines, start=3):
        guide[f"A{i}"] = line
        guide[f"A{i}"].alignment = Alignment(wrap_text=True)
    guide.column_dimensions["A"].width = 90

    daily = wb.create_sheet("گزارش روزانه")
    daily_headers = [
        "تاریخ",
        "فاز EPC",
        "شیفت",
        "ناحیه",
        "هوا",
        "حداقل دما",
        "حداکثر دما",
        "نیروی انسانی",
        "شرح کار",
        "مشکلات و تأخیر",
        "حوادث ایمنی",
        "مشاهدات HSE",
        "Near Miss",
        "ساعت توقف",
        "بازدید / جلسات",
        "یادداشت",
    ]
    daily.append(daily_headers)
    style_header_row(daily)
    daily.append(
        [
            format_jalali(date.today()),
            "اجرا",
            "روزکار",
            "ناحیه A",
            "آفتابی",
            18,
            34,
            42,
            "بتن‌ریزی فونداسیون پمپ‌ها و نصب بولت‌ها",
            "تأخیر در رسیدن میکسر",
            "",
            "استفاده از PPE کامل",
            0,
            1.5,
            "بازدید کارفرما ساعت ۱۰",
            "",
        ]
    )
    autosize(daily)

    mp = wb.create_sheet("نیروی انسانی")
    mp.append(["تاریخ", "نقش", "تعداد"])
    style_header_row(mp, fill_hex="0B6480")
    today = format_jalali(date.today())
    for role, count in (("کارگر ساده", 20), ("جوشکار", 6), ("راننده", 4), ("سرپرست کارگاه", 2)):
        mp.append([today, role, count])
    autosize(mp)

    eq = wb.create_sheet("ماشین آلات")
    eq.append(["تاریخ", "نام", "تعداد", "ساعت کار"])
    style_header_row(eq, fill_hex="D97706")
    eq.append([today, "بیل مکانیکی", 1, 8])
    eq.append([today, "کمپرسی", 3, 6])
    autosize(eq)

    pr = wb.create_sheet("پیشرفت")
    pr.append(["تاریخ", "شناسه آیتم", "کد WBS", "درصد پیشرفت", "مقدار انجام‌شده", "یادداشت"])
    style_header_row(pr, fill_hex="4F46E5")
    if items:
        for it in items[:8]:
            pr.append(
                [
                    today,
                    it.id,
                    it.wbs_code or it.pms_item_number or "",
                    float(it.actual_progress_percentage or 0),
                    "",
                    it.title,
                ]
            )
    else:
        pr.append([today, "", "1.2.3", 35, 12, "نمونه — کد WBS را با آیتم پروژه جایگزین کنید"])
    autosize(pr)

    mat = wb.create_sheet("مصالح")
    mat.append(["تاریخ", "نام", "مقدار", "واحد", "تأمین‌کننده"])
    style_header_row(mat, fill_hex="059669")
    mat.append([today, "سیمان تیپ ۲", 40, "تن", "سیمان تهران"])
    autosize(mat)

    ref = wb.create_sheet("آیتم های پروژه")
    ref.append(["شناسه", "کد WBS", "شماره PMS", "عنوان", "دیسیپلین", "درصد فعلی"])
    style_header_row(ref, fill_hex="334155")
    for it in items or []:
        ref.append(
            [
                it.id,
                it.wbs_code or "",
                it.pms_item_number or "",
                it.title,
                it.discipline or it.l4_discipline or "",
                float(it.actual_progress_percentage or 0),
            ]
        )
    if not items:
        ref.append(["—", "—", "—", "هنوز آیتمی در قراردادهای این پروژه نیست", "", ""])
    autosize(ref)

    # light fill for guide
    guide["A3"].fill = PatternFill("solid", fgColor="EEF8FB")
    return wb


def export_reports_workbook(project, reports: List[DailyReport]):
    ox = require_openpyxl()
    if not ox:
        raise RuntimeError("openpyxl نصب نیست.")
    wb = ox["Workbook"]()
    ws = wb.active
    ws.title = "گزارش روزانه"
    ws.append(
        [
            "تاریخ",
            "تاریخ خورشیدی",
            "وضعیت",
            "فاز EPC",
            "شیفت",
            "ناحیه",
            "هوا",
            "حداقل دما",
            "حداکثر دما",
            "نیروی انسانی",
            "شرح کار",
            "مشکلات",
            "حوادث",
            "مشاهدات HSE",
            "Near Miss",
            "ساعت توقف",
            "بازدید",
            "یادداشت",
            "ارسال‌کننده",
        ]
    )
    style_header_row(ws)
    for r in reports:
        sender = ""
        if r.submitted_by:
            sender = r.submitted_by.full_name or r.submitted_by.email or ""
        ws.append(
            [
                r.report_date.isoformat() if r.report_date else "",
                format_jalali(r.report_date) if r.report_date else "",
                r.status_label,
                r.epc_phase_label if r.epc_phase else "",
                r.shift_label if r.shift else "",
                r.work_area or "",
                r.weather_label,
                float(r.temperature_min) if r.temperature_min is not None else "",
                float(r.temperature_max) if r.temperature_max is not None else "",
                r.manpower_total or 0,
                r.work_performed or "",
                r.issues_delays or "",
                r.hse_incidents or "",
                r.hse_observations or "",
                r.near_miss_count or 0,
                float(r.lost_time_hours) if r.lost_time_hours is not None else "",
                r.visitors_meetings or "",
                r.notes or "",
                sender,
            ]
        )
    autosize(ws)

    mp = wb.create_sheet("نیروی انسانی")
    mp.append(["تاریخ", "نقش", "تعداد"])
    style_header_row(mp, fill_hex="0B6480")
    eq = wb.create_sheet("ماشین آلات")
    eq.append(["تاریخ", "نام", "تعداد", "ساعت کار"])
    style_header_row(eq, fill_hex="D97706")
    pr = wb.create_sheet("پیشرفت")
    pr.append(["تاریخ", "شناسه آیتم", "درصد", "مقدار", "یادداشت"])
    style_header_row(pr, fill_hex="4F46E5")
    mat = wb.create_sheet("مصالح")
    mat.append(["تاریخ", "نام", "مقدار", "واحد", "تأمین‌کننده"])
    style_header_row(mat, fill_hex="059669")
    for r in reports:
        d = r.report_date.isoformat() if r.report_date else ""
        for row in r.manpower_details or []:
            mp.append([d, row.get("role"), row.get("count")])
        for row in r.equipment_details or []:
            eq.append([d, row.get("name"), row.get("count"), row.get("hours")])
        for row in r.progress_updates or []:
            pr.append(
                [
                    d,
                    row.get("contract_item_id"),
                    row.get("progress_percent"),
                    row.get("quantity_done"),
                    row.get("notes"),
                ]
            )
        for row in r.materials_received or []:
            mat.append([d, row.get("name"), row.get("qty"), row.get("unit"), row.get("vendor")])
    autosize(mp)
    autosize(eq)
    autosize(pr)
    autosize(mat)
    return wb


def _sheet_by_aliases(wb, names: Tuple[str, ...]):
    want = {n.replace(" ", "").lower() for n in names}
    for ws in wb.worksheets:
        title = (ws.title or "").replace(" ", "").replace("_", "").lower()
        if title in want:
            return ws
    return None


def _index_project_items(project) -> Dict[str, ContractItem]:
    mapping: Dict[str, ContractItem] = {}
    for contract in project.contracts:
        for it in contract.items:
            mapping[str(it.id)] = it
            if it.wbs_code:
                mapping[str(it.wbs_code).strip().lower()] = it
            if it.pms_item_number:
                mapping[str(it.pms_item_number).strip().lower()] = it
            if it.activity_id:
                mapping[str(it.activity_id).strip().lower()] = it
    return mapping


def _resolve_item(row_idx, row, item_map: Dict[str, ContractItem]) -> Optional[ContractItem]:
    item_id = cell(row, row_idx, "contract_item_id")
    wbs = cell(row, row_idx, "wbs_code")
    for raw in (item_id, wbs):
        if raw is None or raw == "":
            continue
        key = str(raw).strip().lower()
        if key.endswith(".0"):
            key = key[:-2]
        found = item_map.get(key)
        if found:
            return found
    return None


def import_daily_reports_from_workbook(
    *,
    project,
    file_storage,
    user_id: int,
    submit_after: bool = False,
) -> Dict[str, Any]:
    ox = require_openpyxl()
    if not ox:
        raise RuntimeError("برای ورود اکسل باید پکیج openpyxl نصب باشد.")

    wb = ox["load_workbook"](file_storage, data_only=True)
    daily_ws = _sheet_by_aliases(
        wb, ("گزارش روزانه", "گزارشروزانه", "daily", "dailyreport", "sheet1")
    ) or wb.worksheets[0]

    headers, rows = iter_data_rows(daily_ws)
    idx = header_index(headers, DAILY_ALIASES)
    if "report_date" not in idx:
        # try second row as English keys
        all_rows = list(daily_ws.iter_rows(values_only=True))
        if len(all_rows) >= 2:
            idx2 = header_index(list(all_rows[1]), DAILY_ALIASES)
            if "report_date" in idx2:
                idx = idx2
                rows = [(i + 3, tuple(r)) for i, r in enumerate(all_rows[2:]) if r and any(r)]

    if "report_date" not in idx:
        raise ValueError("ستون «تاریخ» در برگه گزارش روزانه یافت نشد.")

    grouped: Dict[date, Dict[str, Any]] = {}
    skipped = 0
    errors: List[str] = []

    for line_no, row in rows:
        report_date = parse_excel_date(cell(row, idx, "report_date"))
        if not report_date:
            skipped += 1
            errors.append(f"ردیف {line_no}: تاریخ نامعتبر")
            continue
        if report_date > date.today():
            skipped += 1
            errors.append(f"ردیف {line_no}: تاریخ آینده مجاز نیست")
            continue
        payload = grouped.setdefault(
            report_date,
            {
                "epc_phase": None,
                "shift": None,
                "work_area": None,
                "weather": None,
                "temperature_min": None,
                "temperature_max": None,
                "manpower_total": 0,
                "work_performed": [],
                "issues_delays": [],
                "hse_incidents": [],
                "hse_observations": [],
                "near_miss_count": 0,
                "lost_time_hours": None,
                "visitors_meetings": [],
                "notes": [],
                "manpower_details": [],
                "equipment_details": [],
                "progress_updates": [],
                "materials_received": [],
            },
        )
        payload["epc_phase"] = payload["epc_phase"] or _map_choice(cell(row, idx, "epc_phase"), PHASE_MAP)
        payload["shift"] = payload["shift"] or _map_choice(cell(row, idx, "shift"), SHIFT_MAP)
        payload["work_area"] = payload["work_area"] or cell(row, idx, "work_area")
        weather_raw = cell(row, idx, "weather")
        payload["weather"] = payload["weather"] or _map_choice(weather_raw, WEATHER_MAP)
        if cell(row, idx, "temperature_min") is not None:
            payload["temperature_min"] = to_float(cell(row, idx, "temperature_min"))
        if cell(row, idx, "temperature_max") is not None:
            payload["temperature_max"] = to_float(cell(row, idx, "temperature_max"))
        mp = to_int(cell(row, idx, "manpower_total"), 0) or 0
        payload["manpower_total"] = max(int(payload["manpower_total"] or 0), mp)
        for key in (
            "work_performed",
            "issues_delays",
            "hse_incidents",
            "hse_observations",
            "visitors_meetings",
            "notes",
        ):
            val = cell(row, idx, key)
            if val:
                payload[key].append(str(val))
        nm = to_int(cell(row, idx, "near_miss_count"), 0) or 0
        payload["near_miss_count"] = int(payload["near_miss_count"] or 0) + nm
        if cell(row, idx, "lost_time_hours") is not None:
            payload["lost_time_hours"] = to_float(cell(row, idx, "lost_time_hours"))

    def _ingest_child(ws, aliases, builder):
        if ws is None:
            return
        h, data = iter_data_rows(ws)
        ix = header_index(h, aliases)
        if "report_date" not in ix:
            return
        for line_no, row in data:
            d = parse_excel_date(cell(row, ix, "report_date"))
            if not d:
                continue
            payload = grouped.setdefault(
                d,
                {
                    "epc_phase": None,
                    "shift": None,
                    "work_area": None,
                    "weather": None,
                    "temperature_min": None,
                    "temperature_max": None,
                    "manpower_total": 0,
                    "work_performed": [],
                    "issues_delays": [],
                    "hse_incidents": [],
                    "hse_observations": [],
                    "near_miss_count": 0,
                    "lost_time_hours": None,
                    "visitors_meetings": [],
                    "notes": [],
                    "manpower_details": [],
                    "equipment_details": [],
                    "progress_updates": [],
                    "materials_received": [],
                },
            )
            builder(payload, ix, row)

    item_map = _index_project_items(project)

    def add_manpower(payload, ix, row):
        role = cell(row, ix, "role")
        if not role:
            return
        payload["manpower_details"].append({"role": str(role), "count": to_int(cell(row, ix, "count"), 0) or 0})

    def add_equipment(payload, ix, row):
        name = cell(row, ix, "name")
        if not name:
            return
        payload["equipment_details"].append(
            {
                "name": str(name),
                "count": to_int(cell(row, ix, "count"), 1) or 1,
                "hours": to_float(cell(row, ix, "hours"), 0) or 0,
            }
        )

    def add_progress(payload, ix, row):
        item = _resolve_item(ix, row, item_map)
        notes = cell(row, ix, "notes") or ""
        payload["progress_updates"].append(
            {
                "contract_item_id": item.id if item else to_int(cell(row, ix, "contract_item_id")),
                "progress_percent": to_float(cell(row, ix, "progress_percent")),
                "quantity_done": to_float(cell(row, ix, "quantity_done")),
                "notes": str(notes),
                "wbs_code": str(cell(row, ix, "wbs_code") or ""),
            }
        )

    def add_materials(payload, ix, row):
        name = cell(row, ix, "name")
        if not name:
            return
        payload["materials_received"].append(
            {
                "name": str(name),
                "qty": to_float(cell(row, ix, "qty")),
                "unit": str(cell(row, ix, "unit") or ""),
                "vendor": str(cell(row, ix, "vendor") or ""),
            }
        )

    _ingest_child(
        _sheet_by_aliases(wb, ("نیروی انسانی", "نیرویانسانی", "manpower")),
        MANPOWER_ALIASES,
        add_manpower,
    )
    _ingest_child(
        _sheet_by_aliases(wb, ("ماشین آلات", "ماشینآلات", "تجهیزات", "equipment")),
        EQUIPMENT_ALIASES,
        add_equipment,
    )
    _ingest_child(
        _sheet_by_aliases(wb, ("پیشرفت", "progress")),
        PROGRESS_ALIASES,
        add_progress,
    )
    _ingest_child(
        _sheet_by_aliases(wb, ("مصالح", "مواد", "materials")),
        MATERIALS_ALIASES,
        add_materials,
    )

    created = 0
    updated = 0
    untouched = 0

    def _join(values: List[str]) -> Optional[str]:
        parts = [v.strip() for v in values if v and str(v).strip()]
        return "\n".join(parts) if parts else None

    for report_date, payload in sorted(grouped.items()):
        existing = DailyReport.query.filter_by(
            project_id=project.id,
            report_date=report_date,
            submitted_by_id=user_id,
        ).first()
        if existing and existing.status not in ("draft", "needs_revision"):
            untouched += 1
            errors.append(f"{report_date}: گزارش موجود در وضعیت «{existing.status_label}» است و به‌روز نشد.")
            continue

        mp_details = payload["manpower_details"]
        mp_total = int(payload["manpower_total"] or 0)
        if mp_details and not mp_total:
            mp_total = sum(int(x.get("count") or 0) for x in mp_details)

        fields = dict(
            weather=payload["weather"],
            temperature_min=payload["temperature_min"],
            temperature_max=payload["temperature_max"],
            manpower_total=mp_total,
            manpower_details=mp_details or None,
            equipment_details=payload["equipment_details"] or None,
            work_performed=_join(payload["work_performed"]),
            progress_updates=payload["progress_updates"] or None,
            issues_delays=_join(payload["issues_delays"]),
            hse_incidents=_join(payload["hse_incidents"]),
            hse_observations=_join(payload["hse_observations"]),
            near_miss_count=int(payload["near_miss_count"] or 0),
            visitors_meetings=_join(payload["visitors_meetings"]),
            notes=_join(payload["notes"]),
            epc_phase=payload["epc_phase"],
            work_area=payload["work_area"],
            shift=payload["shift"],
            lost_time_hours=payload["lost_time_hours"],
            materials_received=payload["materials_received"] or None,
        )

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.add_history(
                user_id=user_id,
                action="excel_import",
                from_status=existing.status,
                to_status=existing.status,
                comment="به‌روزرسانی از اکسل",
            )
            if submit_after and existing.is_editable:
                existing.submit(user_id)
            updated += 1
            continue

        report = DailyReport(
            company_id=project.company_id,
            project_id=project.id,
            report_date=report_date,
            submitted_by_id=user_id,
            status="draft",
            **fields,
        )
        db.session.add(report)
        db.session.flush()
        report.add_history(
            user_id=user_id,
            action="excel_import",
            from_status=None,
            to_status="draft",
            comment="ایجاد از اکسل",
        )
        if submit_after:
            report.submit(user_id)
        created += 1

    db.session.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "untouched": untouched,
        "errors": errors[:12],
        "dates": len(grouped),
    }


def dumps_rows(rows: Optional[list]) -> str:
    if not rows:
        return "[]"
    return json.dumps(rows, ensure_ascii=False)
