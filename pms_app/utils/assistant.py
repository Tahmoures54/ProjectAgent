# Path: pms_app/utils/assistant.py
"""
In-app help assistant: keyword FAQ for Project Agent (no external LLM required).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from flask import url_for


def _url(endpoint: str, **values) -> Optional[str]:
    try:
        return url_for(endpoint, **values)
    except Exception:
        return None


FAQ: List[Tuple[Tuple[str, ...], str, Optional[str], str]] = [
    (
        ("گزارش روزانه", "daily report", "گزارش کارگاه", "ثبت گزارش"),
        "از منوی «گزارش روزانه» پروژه را انتخاب کنید، پیش‌نویس بسازید و ارسال کنید. پیشرفت آیتم‌ها فقط بعد از تأیید مدیر اعمال می‌شود.",
        "daily_reports.index",
        "رفتن به گزارش روزانه",
    ),
    (
        ("تأیید گزارش", "approve", "رد گزارش", "نیاز به اصلاح"),
        "مدیران پروژه می‌توانند گزارش ارسال‌شده را تأیید، رد، یا برای اصلاح برگردانند. گردش کار: پیش‌نویس → ارسال → بررسی → تأیید/رد/اصلاح.",
        "daily_reports.index",
        "گزارش‌های در انتظار",
    ),
    (
        ("کانسرن", "concern", "دغدغه", "مسئله"),
        "کانسرن برای ثبت ریسک و مانع کاری است. سطح مشاهده را درست انتخاب کنید: خصوصی، اعضای پروژه، فقط مدیران، یا کل شرکت.",
        "concerns.index",
        "رفتن به کانسرن‌ها",
    ),
    (
        ("evm", "cpi", "spi", "s-curve", "ارزش کسب", "بودجه"),
        "در صفحه هر پروژه شاخص‌های EVM (BAC, EV, AC, CPI, SPI) و نمودار S-Curve نمایش داده می‌شود. آیتم‌ها باید بودجه و پیشرفت داشته باشند.",
        "projects.projects",
        "لیست پروژه‌ها",
    ),
    (
        ("قرارداد", "صورت وضعیت", "cbs", "آیتم"),
        "قراردادها زیر هر پروژه هستند. آیتم‌ها ساختار WBS/CBS و پیشرفت را نگه می‌دارند و می‌توان آن‌ها را از اکسل وارد کرد.",
        "projects.projects",
        "پروژه‌ها و قراردادها",
    ),
    (
        ("ورود", "رمز", "پسورد", "password", "2fa", "دو مرحله"),
        "از صفحه ورود با ایمیل وارد شوید. اگر Authenticator فعال باشد بعد از رمز، کد ۶ رقمی Google یا Microsoft Authenticator لازم است. فعال‌سازی از منوی کاربر → ورود دو مرحله‌ای، با اسکن بارکد.",
        "auth.change_password",
        "ورود دو مرحله‌ای",
    ),
    (
        ("جستجو", "search", "پیدا کردن"),
        "از نوار جستجوی بالا عبارت بزنید تا همزمان در پروژه‌ها، گزارش‌های روزانه و کانسرن‌ها جستجو شود.",
        "main.search",
        "صفحه جستجو",
    ),
    (
        ("داشبورد", "dashboard", "آمار"),
        "داشبورد تعداد پروژه‌ها، قراردادهای فعال، تأخیردارها، گزارش‌های در انتظار تأیید و کانسرن‌های باز را نشان می‌دهد.",
        "main.dashboard",
        "داشبورد",
    ),
    (
        ("نقش", "دسترسی", "rbac", "پیمانکار", "مدیر"),
        "نقش‌ها: مالک/ادمین پلتفرم، ادمین شرکت، مدیر پروژه، پیمانکار، مشاهده‌گر. پیمانکار گزارش روزانه می‌نویسد؛ مدیر تأیید می‌کند.",
        "main.help",
        "راهنما",
    ),
    (
        ("سلام", "hi", "hello", "کمک", "help"),
        "سلام! می‌توانید بپرسید: گزارش روزانه، کانسرن، EVM، جستجو، یا نقش‌ها. برای کار عملی از داشبورد شروع کنید.",
        "main.help",
        "راهنمای سامانه",
    ),
]


def answer_question(question: str) -> Dict[str, Optional[str]]:
    q = (question or "").strip().lower()
    if not q:
        return {
            "ok": False,
            "answer": "سؤال را بنویسید؛ مثلاً «گزارش روزانه چطور ثبت می‌شود؟»",
            "url": None,
            "cta": None,
        }

    best = None
    best_score = 0
    for keywords, text, endpoint, cta in FAQ:
        score = sum(1 for kw in keywords if kw.lower() in q)
        if score > best_score:
            best_score = score
            best = (text, endpoint, cta)

    if not best or best_score == 0:
        return {
            "ok": True,
            "answer": (
                "پاسخ دقیقی برای این عبارت ندارم. این‌ها را امتحان کنید: "
                "گزارش روزانه، کانسرن، EVM، جستجو، نقش‌ها. "
                "از نوار جستجو هم می‌توانید پروژه یا کانسرن را پیدا کنید."
            ),
            "url": _url("main.help"),
            "cta": "راهنما",
        }

    text, endpoint, cta = best
    return {
        "ok": True,
        "answer": text,
        "url": _url(endpoint) if endpoint else None,
        "cta": cta,
    }
