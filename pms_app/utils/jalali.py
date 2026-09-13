# Path: pms_app/utils/jalali.py
"""
Jalali (Solar / Persian) calendar helpers.

Storage: Gregorian in DB
Display / forms: Jalali
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Union

try:
    import jdatetime
except ImportError:  # pragma: no cover
    jdatetime = None  # type: ignore

DateLike = Union[date, datetime, str, None]

JALALI_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)

JALALI_WEEKDAYS = (
    "شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه",
)


def _ensure_jdatetime():
    if jdatetime is None:
        raise RuntimeError("پکیج jdatetime نصب نیست. اجرا کنید: pip install jdatetime")


def _as_gregorian_date(value: DateLike) -> Optional[date]:
    """Normalize various inputs to a Gregorian date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            if "T" in value or " " in value:
                return datetime.fromisoformat(value.replace("Z", "")).date()
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# میلادی → خورشیدی
# ---------------------------------------------------------------------------

def gregorian_to_jalali(value: DateLike) -> Optional[Dict[str, Any]]:
    """
    تبدیل تاریخ میلادی به خورشیدی.

    ورودی: date | datetime | "2024-09-19"
    خروجی نمونه:
      {
        "year": 1403, "month": 6, "day": 29,
        "iso": "1403/06/29",
        "long": "29 شهریور 1403",
        "month_name": "شهریور",
        "weekday": "چهارشنبه",
      }
    """
    g = _as_gregorian_date(value)
    if g is None:
        return None
    _ensure_jdatetime()
    j = jdatetime.date.fromgregorian(date=g)
    # jdatetime weekday: 0=شنبه ... 6=جمعه
    wd = j.weekday()
    return {
        "year": j.year,
        "month": j.month,
        "day": j.day,
        "iso": f"{j.year:04d}/{j.month:02d}/{j.day:02d}",
        "long": f"{j.day} {JALALI_MONTHS[j.month - 1]} {j.year}",
        "month_name": JALALI_MONTHS[j.month - 1],
        "weekday": JALALI_WEEKDAYS[wd] if 0 <= wd < 7 else "",
        "gregorian": g.isoformat(),
    }


def to_jalali(value: DateLike) -> Optional["jdatetime.date"]:
    """Convert Gregorian → jdatetime.date object."""
    g = _as_gregorian_date(value)
    if g is None:
        # maybe already a Jalali string
        if isinstance(value, str):
            return parse_jalali(value)
        return None
    _ensure_jdatetime()
    return jdatetime.date.fromgregorian(date=g)


def format_jalali(
    value: DateLike,
    fmt: str = "%Y/%m/%d",
    *,
    with_month_name: bool = False,
) -> str:
    """رشته خورشیدی از تاریخ میلادی. مثال: 1403/06/29 یا ۲۹ شهریور ۱۴۰۳"""
    info = gregorian_to_jalali(value)
    if info is None:
        return "—"
    if with_month_name:
        return info["long"]
    if fmt == "%Y/%m/%d":
        return info["iso"]
    j = to_jalali(value)
    if j is None:
        return "—"
    try:
        return j.strftime(fmt)
    except Exception:
        return info["iso"]


def format_jalali_month(value: DateLike) -> str:
    info = gregorian_to_jalali(value)
    if info is None:
        return ""
    return f"{info['year']}/{info['month']:02d}"


def format_jalali_month_name(value: DateLike) -> str:
    info = gregorian_to_jalali(value)
    if info is None:
        return ""
    return f"{info['month_name']} {info['year']}"


# ---------------------------------------------------------------------------
# خورشیدی → میلادی
# ---------------------------------------------------------------------------

def to_gregorian(jy: int, jm: int, jd: int) -> date:
    _ensure_jdatetime()
    return jdatetime.date(jy, jm, jd).togregorian()


def parse_jalali(text: str) -> Optional["jdatetime.date"]:
    if not text:
        return None
    _ensure_jdatetime()
    text = text.strip().replace(".", "/").replace("-", "/")
    parts = text.split("/")
    try:
        if len(parts) == 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            if y >= 1700:
                return None
            return jdatetime.date(y, m, d)
        digits = text.replace("/", "")
        if len(digits) == 8 and digits.isdigit():
            y, m, d = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
            if y >= 1700:
                return None
            return jdatetime.date(y, m, d)
    except (ValueError, TypeError):
        return None
    return None


def parse_jalali_to_gregorian(text: str) -> Optional[date]:
    j = parse_jalali(text)
    return j.togregorian() if j else None


def jalali_to_gregorian_dict(text: str) -> Optional[Dict[str, Any]]:
    """خورشیدی (رشته) → دیکشنری میلادی."""
    g = parse_jalali_to_gregorian(text)
    if g is None:
        return None
    return {
        "year": g.year,
        "month": g.month,
        "day": g.day,
        "iso": g.isoformat(),
    }


def jalali_today() -> "jdatetime.date":
    _ensure_jdatetime()
    return jdatetime.date.today()


def days_between(start: DateLike, end: DateLike) -> Optional[int]:
    g1 = _as_gregorian_date(start) or (
        parse_jalali_to_gregorian(start) if isinstance(start, str) else None
    )
    g2 = _as_gregorian_date(end) or (
        parse_jalali_to_gregorian(end) if isinstance(end, str) else None
    )
    if g1 is None or g2 is None:
        return None
    return (g2 - g1).days


def add_jalali_months(value: DateLike, months: int) -> Optional[date]:
    j = to_jalali(value)
    if j is None:
        return None
    _ensure_jdatetime()
    y, m, d = j.year, j.month, j.day
    m += months
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    for day in range(d, 0, -1):
        try:
            return jdatetime.date(y, m, day).togregorian()
        except ValueError:
            continue
    return None
