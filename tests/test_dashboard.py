# tests/test_dashboard.py
from __future__ import annotations

from datetime import date, timedelta

from pms_app.models import Company, Contract, Project, Role, User
from pms_app.utils.assistant import answer_question
from pms_app.utils.inbox import dashboard_kpis


def _user(session, prefix, role_name, company_id=None):
    user = User(
        email=f"{prefix}@example.com",
        full_name=prefix,
        is_active=True,
        company_id=company_id,
    )
    user.set_password("pass1234")
    role = Role.query.filter_by(name=role_name).first()
    if role:
        user.roles = [role]
    session.add(user)
    session.commit()
    return user


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_debug_routes_hidden_when_not_debug(client):
    assert client.get("/debug-static").status_code == 404
    assert client.get("/test-images").status_code == 404


def test_search_requires_login(client):
    assert client.get("/search?q=test").status_code in (302, 401)


def test_dashboard_kpis_and_page(client, db_session):
    company = Company(name="Dash Co")
    db_session.add(company)
    db_session.flush()
    admin = _user(db_session, "dash_admin", "company_admin", company.id)
    active = Project(
        company_id=company.id,
        project_code="PRJ-ON",
        project_name="Ongoing Tower",
        industry="construction",
        base_currency="IRR",
        status="active",
        finish_date=date.today() + timedelta(days=30),
    )
    delayed = Project(
        company_id=company.id,
        project_code="PRJ-DL",
        project_name="Delayed Plant",
        industry="oil_gas",
        base_currency="IRR",
        status="active",
        finish_date=date.today() - timedelta(days=10),
    )
    db_session.add_all([active, delayed])
    db_session.flush()
    db_session.add(
        Contract(
            company_id=company.id,
            project_id=active.id,
            contract_number="CNT-1",
            contract_title="EPC",
            contract_type="EPC",
            pricing_model="lumpsum",
            currency="IRR",
            status="active",
        )
    )
    db_session.commit()

    kpis = dashboard_kpis(admin)
    assert kpis["total_projects"] == 2
    assert kpis["ongoing_projects"] == 2
    assert kpis["delayed_projects"] == 1
    assert kpis["total_contracts"] == 1
    assert delayed.status_title == "فعال"
    assert delayed.is_delayed is True

    client.post("/login", data={"email": admin.email, "password": "pass1234"})
    page = client.get("/dashboard")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Ongoing Tower" in html
    assert "Delayed Plant" in html
    assert "قراردادهای فعال" in html

    search = client.get("/search?q=Delayed")
    assert search.status_code == 200
    assert "Delayed Plant" in search.get_data(as_text=True)


def test_assistant_answers_daily_report():
    result = answer_question("گزارش روزانه چطور ثبت می‌شود؟")
    assert result["ok"] is True
    assert "گزارش روزانه" in result["answer"]


def test_assistant_http(client):
    response = client.post("/assistant/ask", json={"q": "کانسرن چیست"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert "کانسرن" in data["answer"]
