# Path: pms_app/blueprints/projects/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    DecimalField,
    SubmitField,
    HiddenField,
)
from wtforms.validators import DataRequired, Optional, Length, NumberRange

from pms_app.utils.fields import JalaliDateField


class ProjectForm(FlaskForm):
    project_code = StringField("کد پروژه", validators=[DataRequired(), Length(max=50)])
    project_name = StringField("نام پروژه", validators=[DataRequired(), Length(max=200)])
    industry = SelectField(
        "صنعت",
        choices=[
            ("oil_gas", "نفت و گاز"),
            ("epc", "EPC / پیمانکاری جامع"),
            ("construction", "عمران و ساخت"),
            ("power", "نیرو"),
            ("mining", "معدن"),
            ("infra", "زیرساخت"),
            ("other", "سایر"),
        ],
        validators=[DataRequired()],
    )
    client_name = StringField("کارفرما", validators=[Optional(), Length(max=200)])
    location = StringField("موقعیت", validators=[Optional(), Length(max=200)])
    base_currency = SelectField(
        "ارز پایه",
        choices=[("IRR", "ریال"), ("USD", "دلار"), ("EUR", "یورو")],
        default="IRR",
    )
    start_date = JalaliDateField("تاریخ شروع (خورشیدی)", validators=[Optional()])
    finish_date = JalaliDateField("تاریخ پایان (خورشیدی)", validators=[Optional()])
    status = SelectField(
        "وضعیت",
        choices=[
            ("active", "فعال"),
            ("on_hold", "متوقف"),
            ("completed", "تکمیل‌شده"),
            ("cancelled", "لغو شده"),
        ],
        default="active",
    )
    remarks = TextAreaField("توضیحات", validators=[Optional()])
    submit = SubmitField("ذخیره")

    def __init__(self, *args, project_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._project_id = project_id


class InviteToProjectForm(FlaskForm):
    email = StringField("ایمیل", validators=[DataRequired(), Length(max=120)])
    full_name = StringField("نام و نام خانوادگی", validators=[Optional(), Length(max=120)])
    role = SelectField(
        "نقش در پروژه",
        choices=[
            ("admin", "ادمین پروژه"),
            ("manager", "مدیر"),
            ("member", "عضو"),
            ("contractor", "پیمانکار"),
            ("viewer", "مشاهده‌گر"),
        ],
        default="member",
    )
    submit = SubmitField("دعوت")


class ActionItemForm(FlaskForm):
    title = StringField("عنوان اقدام", validators=[DataRequired(), Length(max=250)])
    description = TextAreaField("شرح", validators=[Optional()])
    status = SelectField(
        "وضعیت",
        choices=[
            ("open", "باز"),
            ("in_progress", "در حال انجام"),
            ("done", "انجام‌شده"),
            ("blocked", "مسدود"),
            ("cancelled", "لغو شده"),
        ],
        default="open",
    )
    priority = SelectField(
        "اولویت",
        choices=[
            ("low", "کم"),
            ("medium", "متوسط"),
            ("high", "بالا"),
            ("critical", "بحرانی"),
        ],
        default="medium",
    )
    assignee_id = SelectField("مسئول", coerce=int, validators=[Optional()], choices=[])
    due_date = JalaliDateField("مهلت (خورشیدی)", validators=[Optional()])
    progress_percent = DecimalField(
        "پیشرفت (%)",
        validators=[Optional(), NumberRange(min=0, max=100)],
        places=1,
    )
    contract_item_id = SelectField(
        "مرتبط با فعالیت زمان‌بندی",
        coerce=int,
        validators=[Optional()],
        choices=[],
    )
    submit = SubmitField("ذخیره اقدام")


class ScheduleItemQuickForm(FlaskForm):
    item_id = HiddenField()
    baseline_start_date = JalaliDateField("شروع برنامه", validators=[Optional()])
    baseline_end_date = JalaliDateField("پایان برنامه", validators=[Optional()])
    actual_progress_percentage = DecimalField(
        "پیشرفت (%)",
        validators=[Optional(), NumberRange(min=0, max=100)],
        places=1,
    )
    status = SelectField(
        "وضعیت",
        choices=[
            ("open", "باز"),
            ("in_progress", "در حال انجام"),
            ("completed", "تکمیل"),
            ("on_hold", "متوقف"),
        ],
        validators=[Optional()],
    )
    submit = SubmitField("بروزرسانی")
