# tests/test_home.py
from __future__ import annotations


def test_homepage_is_public_and_has_real_ctas(client, app):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Project Agent" in html
    assert "/register" in html or "ثبت‌نام" in html
    assert "شروع رایگان" in html
    assert "EVM" in html
    assert "گزارش روزانه" in html
    assert "کانسرن" in html
    assert "کنترل پروژه" in html
    assert "home-modules" in html
    assert "home-skin" in html
    assert "hero" in html
    assert "banner-stage" in html
    assert "feature-banner" in html
    assert "/pricing" in html
    assert "data-play-cards" not in html
    assert "home-marquee" not in html
    assert "bento" not in html
    assert "دفتر فنی" not in html


def test_homepage_has_no_fake_metrics_or_quotes(client):
    html = client.get("/").get_data(as_text=True)
    forbidden = (
        "۱۵۰",
        "1200",
        "۱۲۰۰",
        "پروژه تحت کنترل",
        "کاربر فعال",
        "مهندس رضایی",
        "مهندس موسوی",
        "دکتر احمدی",
        "شرکت آبان",
        "هلدینگ پارس",
        "بیش از ۵۰۰ تیم",
        "aggregateRating",
        "ratingCount",
        "۴.۸",
        "4.8",
        "۴۵K",
        "45K",
        "99.9",
        "نسخه ۲.۰",
        "۳,۹۰۰,۰۰۰",
        "۳٫۹۰۰٫۰۰۰",
    )
    for snippet in forbidden:
        assert snippet not in html, snippet


def test_homepage_uses_configured_free_days(client, app):
    app.config["FREE_DAYS"] = 90
    html = client.get("/").get_data(as_text=True)
    assert "۹۰" in html or "90" in html


def test_guest_homepage_hides_app_dock(client):
    html = client.get("/").get_data(as_text=True)
    assert "dock-container" not in html
    assert "پلن‌ها" in html
    assert "شروع رایگان" in html
