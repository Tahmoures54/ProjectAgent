# Path: pms_app/blueprints/auth/forms.py
from __future__ import annotations

from flask_wtf import FlaskForm
from sqlalchemy import func
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, Regexp, ValidationError

from pms_app.models.user import User


class LoginForm(FlaskForm):
    email = StringField("ایمیل", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("رمز عبور", validators=[DataRequired()])
    remember = BooleanField("مرا به خاطر بسپار")
    submit = SubmitField("ورود")


class RegisterForm(FlaskForm):
    # مطابق signup.html
    company_name = StringField("نام شرکت", validators=[DataRequired(), Length(max=120)])
    full_name = StringField("نام و نام خانوادگی", validators=[DataRequired(), Length(max=120)])

    # مطابق signup.html (اختیاری)
    phone = StringField(
        "شماره همراه",
        validators=[
            Optional(),
            Length(max=20),
            # اجازه اعداد فارسی/انگلیسی و + و فاصله و خط تیره و پرانتز
            Regexp(r"^[0-9۰-۹+\-\s()]{7,20}$", message="شماره تلفن نامعتبر است."),
        ],
    )

    email = StringField("ایمیل", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("رمز عبور", validators=[DataRequired(), Length(min=8, max=128)])
    password2 = PasswordField(
        "تکرار رمز عبور",
        validators=[DataRequired(), EqualTo("password", message="رمزها یکسان نیستند.")],
    )
    submit = SubmitField("ثبت‌نام")

    def validate_email(self, field):
        """
        چون email در دیتابیس unique است، باید دقیق و نرمال شده چک شود.
        ilike در بعضی DBها ممکن است باعث استفاده نشدن از ایندکس شود.
        """
        email = (field.data or "").strip().lower()
        if not email:
            raise ValidationError("ایمیل نامعتبر است.")

        exists = User.query.filter(func.lower(User.email) == email).first()
        if exists:
            raise ValidationError("این ایمیل قبلاً ثبت شده است.")

    def validate_company_name(self, field):
        name = " ".join((field.data or "").strip().split())
        if not name:
            raise ValidationError("نام شرکت الزامی است.")
        field.data = name  # یکدست‌سازی ورودی


class ForgotPasswordForm(FlaskForm):
    email = StringField("ایمیل", validators=[DataRequired(), Email(), Length(max=120)])
    submit = SubmitField("ارسال لینک بازیابی")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("رمز جدید", validators=[DataRequired(), Length(min=8, max=128)])
    password2 = PasswordField(
        "تکرار رمز جدید",
        validators=[DataRequired(), EqualTo("password", message="رمزها یکسان نیستند.")],
    )
    submit = SubmitField("تغییر رمز")


class OTPForm(FlaskForm):
    otp_code = StringField(
        "کد ۶ رقمی یا کد پشتیبان",
        validators=[DataRequired(), Length(min=6, max=20)],
    )
    submit = SubmitField("تأیید")


class Disable2FAForm(FlaskForm):
    current_password = PasswordField("رمز فعلی", validators=[DataRequired()])
    submit = SubmitField("غیرفعال کردن")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("رمز فعلی", validators=[DataRequired()])
    new_password = PasswordField("رمز جدید", validators=[DataRequired(), Length(min=8, max=128)])
    new_password2 = PasswordField(
        "تکرار رمز جدید",
        validators=[DataRequired(), EqualTo("new_password", message="رمزها یکسان نیستند.")],
    )
    submit = SubmitField("تغییر رمز")