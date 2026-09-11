# tests/test_projects.py
from __future__ import annotations

from pms_app.models import Role, User, Company, Project


def _create_user(session, email_prefix, password, role_name=None, company_id=None):
    email = f"{email_prefix}@example.com"
    user = User(email=email, full_name=email_prefix, is_active=True, company_id=company_id)
    user.set_password(password)

    if role_name:
        role = Role.query.filter_by(name=role_name).first()
        if role:
            user.roles = [role]

    session.add(user)
    session.commit()
    return user


def test_projects_list_requires_login(client):
    response = client.get("/projects")
    assert response.status_code in (302, 401)


def test_viewer_can_see_projects_list_but_cannot_create(client, db_session):
    company = Company(name="Viewer Co")
    db_session.add(company)
    db_session.commit()
    _create_user(db_session, "viewer1", "pass1234", role_name="viewer", company_id=company.id)

    client.post("/login", data={
        "email": "viewer1@example.com",
        "password": "pass1234",
    })

    response = client.get("/projects")
    assert response.status_code == 200

    response = client.post("/projects/new", data={
        "project_code": "PRJ-X",
        "project_name": "Test",
        "industry": "construction",
        "base_currency": "IRR",
    })
    assert response.status_code in (302, 403)


def test_admin_can_create_project(client, db_session):
    company = Company(name="Admin Co")
    db_session.add(company)
    db_session.commit()
    _create_user(db_session, "admin1", "pass1234", role_name="company_admin", company_id=company.id)
    client.post("/login", data={
        "email": "admin1@example.com",
        "password": "pass1234",
    })

    response = client.post("/projects/new", data={
        "company_id": company.id,
        "project_code": "PRJ-100",
        "project_name": "Admin Project",
        "industry": "construction",
        "base_currency": "IRR",
        "status": "active",
    }, follow_redirects=False)

    assert response.status_code in (301, 302)
    assert Project.query.filter_by(project_code="PRJ-100").first() is not None


def test_admin_can_edit_project(client, db_session):
    company = Company(name="Edit Co")
    db_session.add(company)
    db_session.flush()
    _create_user(db_session, "admin2", "pass1234", role_name="company_admin", company_id=company.id)
    client.post("/login", data={
        "email": "admin2@example.com",
        "password": "pass1234",
    })

    project = Project(
        company_id=company.id,
        project_code="PRJ-EDIT",
        project_name="Edit Project",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    db_session.add(project)
    db_session.commit()

    response = client.post(f"/projects/{project.id}/edit", data={
        "project_name": "Updated Name",
        "industry": "oil_gas",
        "base_currency": "USD",
        "status": "active",
    }, follow_redirects=False)

    assert response.status_code in (301, 302)
    assert Project.query.get(project.id).project_name == "Updated Name"


def test_admin_can_delete_project(client, db_session):
    company = Company(name="Delete Co")
    db_session.add(company)
    db_session.flush()
    _create_user(db_session, "admin3", "pass1234", role_name="company_admin", company_id=company.id)
    client.post("/login", data={
        "email": "admin3@example.com",
        "password": "pass1234",
    })

    project = Project(
        company_id=company.id,
        project_code="PRJ-DEL",
        project_name="Delete Project",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    db_session.add(project)
    db_session.commit()

    response = client.post(f"/projects/{project.id}/delete", follow_redirects=False)
    assert response.status_code in (301, 302)
    assert Project.query.get(project.id) is None