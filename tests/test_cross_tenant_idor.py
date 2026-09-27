from __future__ import annotations

from datetime import date

from pms_app.models import Company, Concern, DailyReport, Project, Role, User
from pms_app.models.project_membership import ProjectMembership


def _role(name):
    return Role.query.filter_by(name=name).first()


def _user(session, prefix, role_name, company_id):
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


def _company_project(session, suffix):
    company = Company(name=f"IDOR Co {suffix}")
    session.add(company)
    session.flush()
    project = Project(
        company_id=company.id,
        project_code=f"IDOR-{suffix}",
        project_name=f"IDOR Project {suffix}",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    session.add(project)
    session.commit()
    return company, project


def _login(client, email):
    response = client.post(
        "/login",
        data={"email": email, "password": "pass1234"},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)


def test_daily_report_idor_is_blocked_across_companies(client, db_session):
    company_a, project_a = _company_project(db_session, "A")
    company_b, project_b = _company_project(db_session, "B")
    admin_b = _user(db_session, "idor_daily_b", "company_admin", company_b.id)
    report_a = DailyReport(
        company_id=company_a.id,
        project_id=project_a.id,
        report_date=date.today(),
        submitted_by_id=admin_b.id,
        status="draft",
        work_performed="SECRET-A",
    )
    db_session.add(report_a)
    db_session.add(
        ProjectMembership(
            project_id=project_b.id,
            user_id=admin_b.id,
            role="admin",
            status="active",
        )
    )
    db_session.commit()

    _login(client, admin_b.email)

    for method, url in (
        ("get", f"/daily-reports/{report_a.id}"),
        ("get", f"/daily-reports/{report_a.id}/edit"),
        ("post", f"/daily-reports/{report_a.id}/submit"),
        ("post", f"/daily-reports/{report_a.id}/delete"),
    ):
        response = getattr(client, method)(url, follow_redirects=False)
        assert response.status_code in (302, 403, 404), (method, url, response.status_code)

    assert DailyReport.query.get(report_a.id).status == "draft"
    assert DailyReport.query.get(report_a.id).work_performed == "SECRET-A"

    # A company-B user must also not retrieve company-A reports through the list filter.
    listing = client.get(f"/daily-reports/?project_id={project_a.id}")
    assert listing.status_code == 200
    assert "SECRET-A" not in listing.get_data(as_text=True)


def test_daily_report_export_and_import_are_project_scoped(client, db_session):
    company_a, project_a = _company_project(db_session, "EXA")
    company_b, project_b = _company_project(db_session, "EXB")
    admin_b = _user(db_session, "idor_export_b", "company_admin", company_b.id)
    db_session.add(
        ProjectMembership(
            project_id=project_b.id,
            user_id=admin_b.id,
            role="admin",
            status="active",
        )
    )
    db_session.add(
        DailyReport(
            company_id=company_a.id,
            project_id=project_a.id,
            report_date=date.today(),
            submitted_by_id=admin_b.id,
            status="draft",
            work_performed="SECRET-EXPORT-A",
        )
    )
    db_session.commit()

    _login(client, admin_b.email)

    export = client.get(f"/daily-reports/project/{project_a.id}/export.xlsx")
    assert export.status_code in (403, 404)

    template = client.get(f"/daily-reports/project/{project_a.id}/template.xlsx")
    assert template.status_code in (403, 404)

    # The target project itself remains accessible to the tenant admin.
    own_template = client.get(f"/daily-reports/project/{project_b.id}/template.xlsx")
    assert own_template.status_code in (200, 302)


def test_concern_idor_is_blocked_across_companies(client, db_session):
    company_a, project_a = _company_project(db_session, "CA")
    company_b, project_b = _company_project(db_session, "CB")
    admin_b = _user(db_session, "idor_concern_b", "company_admin", company_b.id)
    concern_a = Concern(
        company_id=company_a.id,
        project_id=project_a.id,
        title="SECRET-CONCERN-A",
        description="company A confidential data",
        category="technical",
        priority="high",
        visibility="project",
        raised_by_id=admin_b.id,
        status="open",
    )
    db_session.add(concern_a)
    db_session.add(
        ProjectMembership(
            project_id=project_b.id,
            user_id=admin_b.id,
            role="admin",
            status="active",
        )
    )
    db_session.commit()

    _login(client, admin_b.email)

    detail = client.get(f"/concerns/{concern_a.id}")
    assert detail.status_code in (403, 404)
    assert "SECRET-CONCERN-A" not in detail.get_data(as_text=True)

    edit = client.get(f"/concerns/{concern_a.id}/edit")
    assert edit.status_code in (403, 404)

    status = client.post(
        f"/concerns/{concern_a.id}/status",
        data={"action": "close", "note": "cross-tenant attempt"},
        follow_redirects=False,
    )
    assert status.status_code in (302, 403, 404)

    db_session.refresh(concern_a)
    assert concern_a.status == "open"


def test_concern_list_project_filter_cannot_expand_tenant_scope(client, db_session):
    company_a, project_a = _company_project(db_session, "LA")
    company_b, project_b = _company_project(db_session, "LB")
    admin_b = _user(db_session, "idor_list_b", "company_admin", company_b.id)
    db_session.add_all(
        [
            Concern(
                company_id=company_a.id,
                project_id=project_a.id,
                title="SECRET-LIST-A",
                visibility="project",
                raised_by_id=admin_b.id,
                status="open",
                priority="medium",
                category="technical",
            ),
            Concern(
                company_id=company_b.id,
                project_id=project_b.id,
                title="VISIBLE-LIST-B",
                visibility="project",
                raised_by_id=admin_b.id,
                status="open",
                priority="medium",
                category="technical",
            ),
        ]
    )
    db_session.add(
        ProjectMembership(
            project_id=project_b.id,
            user_id=admin_b.id,
            role="admin",
            status="active",
        )
    )
    db_session.commit()

    _login(client, admin_b.email)
    response = client.get(f"/concerns/?project_id={project_a.id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "SECRET-LIST-A" not in html
    assert "VISIBLE-LIST-B" not in html
