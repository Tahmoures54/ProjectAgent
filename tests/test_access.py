# tests/test_access.py
from __future__ import annotations

from datetime import date

from pms_app.models import Company, Contract, ContractItem, DailyReport, Project, Role, User
from pms_app.models.project_membership import ProjectMembership
from pms_app.utils.security import configured_owner_emails


def _role(name):
    return Role.query.filter_by(name=name).first()


def _user(session, prefix, role_name, company_id=None):
    user = User(
        email=f"{prefix}@example.com",
        full_name=prefix,
        is_active=True,
        company_id=company_id,
    )
    user.set_password("pass1234")
    role = _role(role_name)
    if role:
        user.roles = [role]
    session.add(user)
    session.commit()
    return user


def _company_project_contract(session, suffix):
    company = Company(name=f"Co {suffix}")
    session.add(company)
    session.flush()
    project = Project(
        company_id=company.id,
        project_code=f"PRJ-{suffix}",
        project_name=f"Project {suffix}",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    session.add(project)
    session.flush()
    contract = Contract(
        company_id=company.id,
        project_id=project.id,
        contract_number=f"CNT-{suffix}",
        contract_title=f"Contract {suffix}",
        contract_type="EPC",
        pricing_model="lumpsum",
        currency="IRR",
        status="active",
    )
    session.add(contract)
    session.flush()
    item = ContractItem(
        company_id=company.id,
        contract_id=contract.id,
        title=f"Secret item {suffix}",
        status="open",
        priority="medium",
    )
    session.add(item)
    session.commit()
    return company, project, contract, item


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "pass1234"})


def test_items_are_isolated_across_companies(client, db_session):
    _, _, contract_a, item_a = _company_project_contract(db_session, "A")
    company_b, _, _, _ = _company_project_contract(db_session, "B")
    _user(db_session, "admin_a", "company_admin", contract_a.company_id)
    admin_b = _user(db_session, "admin_b", "company_admin", company_b.id)

    _login(client, admin_b.email)

    listing = client.get(f"/contracts/{contract_a.id}/items")
    assert listing.status_code in (403, 404)

    edit = client.get(f"/items/{item_a.id}/edit")
    assert edit.status_code in (403, 404)

    export = client.get(f"/contracts/{contract_a.id}/items/export.csv")
    assert export.status_code in (403, 404)


def test_same_company_non_member_cannot_open_contract_items(client, db_session):
    company, project, contract, item = _company_project_contract(db_session, "M")
    member = _user(db_session, "member_m", "contractor", company.id)
    outsider = _user(db_session, "out_m", "contractor", company.id)
    db_session.add(
        ProjectMembership(project_id=project.id, user_id=member.id, role="member", status="active")
    )
    db_session.commit()

    _login(client, member.email)
    assert client.get(f"/contracts/{contract.id}/items").status_code == 200

    client.get("/logout")
    _login(client, outsider.email)
    assert client.get(f"/contracts/{contract.id}/items").status_code in (403, 404)
    assert client.get(f"/items/{item.id}/edit").status_code in (403, 404)


def test_contracts_are_isolated_across_companies(client, db_session):
    _, project_a, contract_a, _ = _company_project_contract(db_session, "CA")
    company_b, _, _, _ = _company_project_contract(db_session, "CB")
    _user(db_session, "cadmin_a", "company_admin", project_a.company_id)
    admin_b = _user(db_session, "cadmin_b", "company_admin", company_b.id)

    _login(client, admin_b.email)
    assert client.get(f"/projects/{project_a.id}/contracts").status_code in (403, 404)
    assert client.get(f"/contracts/{contract_a.id}/edit").status_code in (403, 404)


def test_reports_hub_is_company_scoped(client, db_session):
    company_a, project_a, _, _ = _company_project_contract(db_session, "RA")
    company_b, project_b, _, _ = _company_project_contract(db_session, "RB")
    admin_a = _user(db_session, "rep_a", "company_admin", company_a.id)
    _user(db_session, "rep_b", "company_admin", company_b.id)

    mine = DailyReport(
        company_id=company_a.id,
        project_id=project_a.id,
        report_date=date.today(),
        status="submitted",
        submitted_by_id=admin_a.id,
        weather="clear",
    )
    other = DailyReport(
        company_id=company_b.id,
        project_id=project_b.id,
        report_date=date.today(),
        status="submitted",
        submitted_by_id=admin_a.id,
        weather="rain",
    )
    db_session.add_all([mine, other])
    db_session.commit()

    _login(client, admin_a.email)
    response = client.get("/reports")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Project RA" in html
    assert "Project RB" not in html
    assert "گزارش‌های سیستمی" not in html


def test_owner_email_is_not_hardcoded(app, db_session):
    user = User(
        email="tahmoures_p@hotmail.com",
        full_name="not-owner",
        is_active=True,
    )
    user.set_password("pass1234")
    db_session.add(user)
    db_session.commit()

    with app.app_context():
        assert configured_owner_emails() == set()
        assert user.is_owner is False
        assert user.is_owner_by_email is False
