# Path: pms_app/utils/fields.py
"""Custom WTForms fields – Jalali date support."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from wtforms import Field
from wtforms.widgets import TextInput

from pms_app.utils.jalali import format_jalali, parse_jalali_to_gregorian


class JalaliDateInput(TextInput):
    """Text input styled for Jalali datepicker."""

    def __call__(self, field, **kwargs):
        kwargs.setdefault("type", "text")
        kwargs.setdefault("dir", "ltr")
        kwargs.setdefault("placeholder", "۱۴۰۳/۰۱/۰۱")
        kwargs.setdefault("autocomplete", "off")
        # class may be a string or list
        extra = "jalali-datepicker"
        if "class" in kwargs:
            kwargs["class"] = f"{kwargs['class']} {extra}".strip()
        elif "class_" in kwargs:
            kwargs["class_"] = f"{kwargs['class_']} {extra}".strip()
        else:
            kwargs["class"] = extra
        kwargs["data-jdp"] = "true"
        return super().__call__(field, **kwargs)


class JalaliDateField(Field):
    """
    Accepts Jalali date strings from the form (e.g. 1403/06/29)
    and stores a Python date (Gregorian) on the field.

    Also accepts ISO Gregorian strings as fallback.
    Display value is always Jalali (YYYY/MM/DD).
    """

    widget = JalaliDateInput()

    def __init__(self, label=None, validators=None, format_display="%Y/%m/%d", **kwargs):
        super().__init__(label, validators, **kwargs)
        self.format_display = format_display

    def _value(self) -> str:
        if self.data is None:
            return ""
        if isinstance(self.data, datetime):
            d = self.data.date()
        elif isinstance(self.data, date):
            d = self.data
        else:
            return str(self.data)
        return format_jalali(d, fmt=self.format_display)

    def process_formdata(self, valuelist):
        if not valuelist or not str(valuelist[0]).strip():
            self.data = None
            return

        raw = str(valuelist[0]).strip()

        year_hint = None
        digits = raw.replace("/", "-").replace(".", "-")
        if len(digits) >= 4 and digits[:4].isdigit():
            year_hint = int(digits[:4])

        # Gregorian ISO (20xx) must not be parsed as Jalali (14xx).
        if year_hint is not None and year_hint >= 1700:
            try:
                if "T" in raw or " " in raw:
                    self.data = datetime.fromisoformat(raw.replace("Z", "")).date()
                else:
                    self.data = date.fromisoformat(digits[:10])
                return
            except ValueError:
                pass

        # 1) Try Jalali
        g = parse_jalali_to_gregorian(raw)
        if g is not None:
            self.data = g
            return

        # 2) Fallback: ISO / Gregorian
        try:
            if "T" in raw or " " in raw:
                self.data = datetime.fromisoformat(raw.replace("Z", "")).date()
            else:
                self.data = date.fromisoformat(raw[:10])
            return
        except ValueError:
            pass

        self.data = None
        raise ValueError("فرمت تاریخ نامعتبر است. مثال: 1403/06/29")
