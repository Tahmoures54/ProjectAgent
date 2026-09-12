# tests/test_access.py
from __future__ import annotations

from datetime import date

from pms_app.models import Company, Concern, Contract, ContractItem, DailyReport, Project, Role, User
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


def test_search_dashboard_and_inbox_hide_other_companies(client, db_session):
    company_a, project_a, _, _ = _company_project_contract(db_session, "SA")
    company_b, project_b, _, _ = _company_project_contract(db_session, "SB")
    admin_a = _user(db_session, "search_a", "company_admin", company_a.id)
    _user(db_session, "search_b", "company_admin", company_b.id)

    db_session.add(
        DailyReport(
            company_id=company_a.id,
            project_id=project_a.id,
            report_date=date.today(),
            status="submitted",
            submitted_by_id=admin_a.id,
            work_performed="excavation unique-alpha",
        )
    )
    db_session.add(
        DailyReport(
            company_id=company_b.id,
            project_id=project_b.id,
            report_date=date.today(),
            status="submitted",
            submitted_by_id=admin_a.id,
            work_performed="excavation unique-beta",
        )
    )
    db_session.add(
        Concern(
            company_id=company_a.id,
            project_id=project_a.id,
            title="leak unique-alpha",
            visibility="company",
            raised_by_id=admin_a.id,
            status="open",
            priority="high",
            category="safety",
        )
    )
    db_session.add(
        Concern(
            company_id=company_b.id,
            project_id=project_b.id,
            title="leak unique-beta",
            visibility="company",
            raised_by_id=admin_a.id,
            status="open",
            priority="high",
            category="safety",
        )
    )
    db_session.commit()

    _login(client, admin_a.email)

    search = client.get("/search?q=unique")
    assert search.status_code == 200
    html = search.get_data(as_text=True)
    assert "unique-alpha" in html
    assert "unique-beta" not in html
    assert "Project SA" in html
    assert "Project SB" not in html

    dash = client.get("/dashboard")
    assert dash.status_code == 200
    dhtml = dash.get_data(as_text=True)
    assert "Project SA" in dhtml or "PRJ-SA" in dhtml
    assert "Project SB" not in dhtml
    assert "PRJ-SB" not in dhtml


def test_concerns_daily_reports_users_projects_isolated(client, db_session):
    company_a, project_a, _, _ = _company_project_contract(db_session, "XA")
    company_b, project_b, _, _ = _company_project_contract(db_session, "XB")
    admin_a = _user(db_session, "iso_a", "company_admin", company_a.id)
    admin_b = _user(db_session, "iso_b", "company_admin", company_b.id)

    report = DailyReport(
        company_id=company_a.id,
        project_id=project_a.id,
        report_date=date.today(),
        status="submitted",
        submitted_by_id=admin_a.id,
    )
    concern = Concern(
        company_id=company_a.id,
        project_id=project_a.id,
        title="secret concern XA",
        visibility="company",
        raised_by_id=admin_a.id,
        status="open",
        priority="medium",
        category="technical",
    )
    db_session.add_all([report, concern])
    db_session.commit()

    _login(client, admin_b.email)
    assert client.get(f"/projects/{project_a.id}").status_code in (403, 404)
    assert client.get(f"/daily-reports/{report.id}").status_code in (403, 404)
    assert client.get(f"/concerns/{concern.id}").status_code in (403, 404)
    assert client.get(f"/users/{admin_a.id}/edit").status_code in (403, 404)


def test_progress_apply_ignores_other_company_items(db_session):
    _, project_a, _, item_a = _company_project_contract(db_session, "PA")
    _, _, _, item_b = _company_project_contract(db_session, "PB")
    admin = _user(db_session, "prog_a", "company_admin", project_a.company_id)
    item_a.actual_progress_percentage = 10
    item_b.actual_progress_percentage = 10
    report = DailyReport(
        company_id=project_a.company_id,
        project_id=project_a.id,
        report_date=date.today(),
        status="submitted",
        submitted_by_id=admin.id,
        progress_updates=[
            {"contract_item_id": item_a.id, "progress_percent": 40},
            {"contract_item_id": item_b.id, "progress_percent": 99},
        ],
    )
    db_session.add(report)
    db_session.commit()

    report.approve(admin.id, apply_progress=True)
    db_session.commit()

    assert float(item_a.actual_progress_percentage) == 40
    assert float(item_b.actual_progress_percentage) == 10


def test_global_settings_are_owner_only(client, db_session):
    company, *_ = _company_project_contract(db_session, "SET")
    admin = _user(db_session, "set_admin", "company_admin", company.id)
    owner = _user(db_session, "set_owner", "owner")

    _login(client, admin.email)
    assert client.get("/settings").status_code == 403
    denied = client.post(
        "/settings",
        data={
            "document_types": "secret-from-tenant",
            "disciplines": "",
            "companies": "",
            "task_statuses": "",
        },
    )
    assert denied.status_code == 403

    client.get("/logout")
    _login(client, owner.email)
    allowed = client.get("/settings")
    assert allowed.status_code == 200
    html = allowed.get_data(as_text=True)
    assert "secret-from-tenant" not in html


def test_managers_only_concern_stays_on_that_project(client, db_session):
    company, project, _, _ = _company_project_contract(db_session, "MO")
    other = Project(
        company_id=company.id,
        project_code="PRJ-MO2",
        project_name="Other project MO",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    db_session.add(other)
    db_session.flush()

    admin = _user(db_session, "mo_admin", "company_admin", company.id)
    company_manager = _user(db_session, "mo_role_mgr", "manager", company.id)
    project_manager = _user(db_session, "mo_pm", "company_user", company.id)
    other_pm = _user(db_session, "mo_other_pm", "manager", company.id)
    db_session.add_all(
        [
            ProjectMembership(
                project_id=project.id,
                user_id=project_manager.id,
                role="manager",
                status="active",
            ),
            ProjectMembership(
                project_id=other.id,
                user_id=other_pm.id,
                role="manager",
                status="active",
            ),
            ProjectMembership(
                project_id=other.id,
                user_id=company_manager.id,
                role="member",
                status="active",
            ),
        ]
    )
    concern = Concern(
        company_id=company.id,
        project_id=project.id,
        title="managers-only secret MO",
        visibility="managers_only",
        raised_by_id=admin.id,
        status="open",
        priority="high",
        category="safety",
    )
    db_session.add(concern)
    db_session.commit()

    assert concern.can_view(admin) is True
    assert concern.can_view(project_manager) is True
    assert concern.can_view(company_manager) is False
    assert concern.can_view(other_pm) is False

    _login(client, company_manager.email)
    listing = client.get("/concerns/")
    assert listing.status_code == 200
    html = listing.get_data(as_text=True)
    assert "managers-only secret MO" not in html
    assert client.get(f"/concerns/{concern.id}").status_code in (403, 404)

    client.get("/logout")
    _login(client, project_manager.email)
    listing = client.get("/concerns/")
    assert "managers-only secret MO" in listing.get_data(as_text=True)
    assert client.get(f"/concerns/{concern.id}").status_code == 200


def test_cannot_invite_other_company_user_to_project(client, db_session):
    _, project_a, _, _ = _company_project_contract(db_session, "IA")
    company_b, _, _, _ = _company_project_contract(db_session, "IB")
    admin_a = _user(db_session, "inv_a", "company_admin", project_a.company_id)
    user_b = _user(db_session, "inv_b", "company_user", company_b.id)

    _login(client, admin_a.email)
    response = client.post(
        f"/projects/{project_a.id}/invite",
        data={"email": user_b.email, "role": "member"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "همان شرکت" not in html
    assert "قابل دعوت به این پروژه نیست" in html
    assert (
        ProjectMembership.query.filter_by(project_id=project_a.id, user_id=user_b.id).first()
        is None
    )

