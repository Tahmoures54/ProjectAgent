# Path: pms_app/blueprints/daily_reports/forms.py
from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    TextAreaField,
    HiddenField,
    BooleanField,
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange, ValidationError

from pms_app.utils.fields import JalaliDateField


class DailyReportForm(FlaskForm):
    """فرم ثبت / ویرایش گزارش روزانه."""

    report_date = JalaliDateField(
        "تاریخ گزارش",
        validators=[DataRequired(message="تاریخ گزارش الزامی است.")],
        default=date.today,
    )

    epc_phase = SelectField(
        "فاز EPC",
        choices=[
            ("", "— انتخاب کنید —"),
            ("engineering", "مهندسی (E)"),
            ("procurement", "تدارکات (P)"),
            ("construction", "اجرا (C)"),
            ("mixed", "ترکیبی / کل پروژه"),
        ],
        validators=[Optional()],
    )
    shift = SelectField(
        "شیفت",
        choices=[
            ("", "—"),
            ("day", "روزکار"),
            ("night", "شب‌کار"),
            ("full", "تمام‌وقت / دو شیفت"),
        ],
        validators=[Optional()],
    )
    work_area = StringField("ناحیه / جبهه کار", validators=[Optional(), Length(max=120)])

    weather = SelectField(
        "وضعیت هوا",
        choices=[
            ("", "— انتخاب کنید —"),
            ("sunny", "آفتابی"),
            ("partly_cloudy", "نیمه‌ابری"),
            ("cloudy", "ابری"),
            ("rainy", "بارانی"),
            ("stormy", "طوفانی"),
            ("snowy", "برفی"),
            ("foggy", "مه"),
            ("windy", "باد شدید"),
            ("other", "سایر"),
        ],
        validators=[Optional()],
    )
    temperature_min = DecimalField("حداقل دما (°C)", places=1, validators=[Optional()])
    temperature_max = DecimalField("حداکثر دما (°C)", places=1, validators=[Optional()])

    manpower_total = IntegerField(
        "تعداد کل نیروی انسانی",
        validators=[Optional(), NumberRange(min=0, max=10000)],
        default=0,
    )
    manpower_details_raw = TextAreaField(
        "جزئیات نیروی انسانی",
        validators=[Optional(), Length(max=8000)],
        render_kw={"rows": 3},
    )

    equipment_details_raw = TextAreaField(
        "ماشین‌آلات و تجهیزات",
        validators=[Optional(), Length(max=8000)],
        render_kw={"rows": 3},
    )

    work_performed = TextAreaField(
        "شرح کارهای انجام‌شده",
        validators=[Optional(), Length(max=10000)],
        render_kw={"rows": 5, "placeholder": "فعالیت‌های اصلی امروز را شرح دهید..."},
    )

    progress_updates_raw = TextAreaField(
        "به‌روزرسانی پیشرفت آیتم‌ها",
        validators=[Optional(), Length(max=12000)],
        render_kw={"rows": 4},
    )

    materials_received_raw = TextAreaField(
        "مصالح و تجهیزات واردشده",
        validators=[Optional(), Length(max=8000)],
        render_kw={"rows": 3},
    )

    engineering_outputs_raw = TextAreaField(
        "خروجی‌های مهندسی",
        validators=[Optional(), Length(max=8000)],
        render_kw={"rows": 3},
    )

    issues_delays = TextAreaField(
        "مشکلات، تأخیرات و موانع",
        validators=[Optional(), Length(max=5000)],
        render_kw={"rows": 3},
    )

    hse_incidents = TextAreaField(
        "حوادث ایمنی (HSE)",
        validators=[Optional(), Length(max=3000)],
        render_kw={"rows": 2},
    )
    hse_observations = TextAreaField(
        "مشاهدات و نکات ایمنی",
        validators=[Optional(), Length(max=3000)],
        render_kw={"rows": 2},
    )
    near_miss_count = IntegerField(
        "تعداد Near Miss",
        validators=[Optional(), NumberRange(min=0, max=1000)],
        default=0,
    )
    lost_time_hours = DecimalField(
        "ساعت توقف کار",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=24)],
    )

    visitors_meetings = TextAreaField(
        "بازدیدکنندگان / جلسات",
        validators=[Optional(), Length(max=2000)],
        render_kw={"rows": 2},
    )

    notes = TextAreaField(
        "یادداشت کلی",
        validators=[Optional(), Length(max=5000)],
        render_kw={"rows": 2},
    )

    action = HiddenField(default="save")

    def validate_report_date(self, field):
        if field.data and field.data > date.today():
            raise ValidationError("تاریخ گزارش نمی‌تواند در آینده باشد.")


class ReviewForm(FlaskForm):
    """فرم تأیید / رد / درخواست اصلاح."""

    action = SelectField(
        "تصمیم",
        choices=[
            ("approve", "تأیید نهایی"),
            ("request_revision", "درخواست اصلاح"),
            ("reject", "رد گزارش"),
        ],
        validators=[DataRequired()],
    )
    comment = TextAreaField(
        "توضیحات / دلیل",
        validators=[Optional(), Length(max=3000)],
        render_kw={"rows": 4, "placeholder": "در صورت رد یا درخواست اصلاح، توضیح الزامی است."},
    )
    apply_progress = SelectField(
        "اعمال پیشرفت روی آیتم‌ها پس از تأیید؟",
        choices=[("yes", "بله – پیشرفت به‌روز شود"), ("no", "خیر – فقط تأیید گزارش")],
        default="yes",
    )


class ImportExcelForm(FlaskForm):
    file = FileField(
        "فایل اکسل",
        validators=[
            FileRequired(message="فایل انتخاب نشده است."),
            FileAllowed(["xlsx", "xls"], message="فقط فایل اکسل (xlsx) مجاز است."),
        ],
    )
    submit_after = BooleanField("پس از ورود، برای تأیید ارسال شود", default=False)
