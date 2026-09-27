# tests/test_projects.py
from __future__ import annotations

from pms_app.models import Role, User, Company, Project, ActionItem, ActionItemHistory


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

def test_action_item_workflow_history_records_status_changes(app, db_session):
    company = Company(name="Audit Co")
    db_session.add(company)
    db_session.flush()
    project = Project(name="Audit Project", company_id=company.id)
    db_session.add(project)
    db_session.flush()
    user = User(email="audit@example.com", company_id=company.id)
    db_session.add(user)
    db_session.flush()

    action = ActionItem(
        company_id=company.id,
        project_id=project.id,
        title="Resolve alert",
        created_by_id=user.id,
        status="open",
    )
    db_session.add(action)
    db_session.flush()
    action.add_history(user_id=user.id, action="created", to_status="open", note="ایجاد")
    action.status = "in_progress"
    action.add_history(user_id=user.id, action="status_change", from_status="open", to_status="in_progress")
    action.mark_done(user.id, "حل شد")
    db_session.commit()

    history = ActionItemHistory.query.filter_by(action_item_id=action.id).order_by(ActionItemHistory.id.asc()).all()
    assert [entry.action for entry in history] == ["created", "status_change", "status_change"]
    assert history[1].from_status == "open"
    assert history[1].to_status == "in_progress"
    assert history[2].to_status == "done"
    assert history[2].note == "حل شد"
    assert history[2].user_id == user.id
