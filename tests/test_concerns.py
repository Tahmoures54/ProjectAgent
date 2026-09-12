# tests/test_concerns.py
from __future__ import annotations

from pms_app.models import Company, Concern, Project, Role, User
from pms_app.models.project_membership import ProjectMembership


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


def test_concerns_list_requires_login(client):
    response = client.get("/concerns/")
    assert response.status_code in (302, 401)


def test_private_concern_visibility(db_session):
    company = Company(name="Vis Co")
    db_session.add(company)
    db_session.flush()
    project = Project(
        company_id=company.id,
        project_code="PRJ-VIS",
        project_name="Visibility",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    db_session.add(project)
    db_session.commit()

    admin = _user(db_session, "vis_admin", "company_admin", company.id)
    raiser = _user(db_session, "vis_raiser", "contractor", company.id)
    outsider = _user(db_session, "vis_out", "contractor", company.id)
    db_session.add(
        ProjectMembership(project_id=project.id, user_id=raiser.id, role="member", status="active")
    )
    db_session.commit()

    concern = Concern(
        company_id=company.id,
        project_id=project.id,
        title="نشت آب در فونداسیون",
        visibility="private",
        raised_by_id=raiser.id,
        status="open",
        priority="high",
        category="safety",
    )
    db_session.add(concern)
    db_session.commit()

    assert concern.can_view(raiser) is True
    assert concern.can_view(admin) is True
    assert concern.can_view(outsider) is False


def test_concern_status_machine(db_session):
    company = Company(name="WF Co")
    db_session.add(company)
    db_session.flush()
    user = _user(db_session, "c_owner", "manager", company.id)
    concern = Concern(
        company_id=company.id,
        title="تأخیر مصالح",
        raised_by_id=user.id,
        status="open",
        priority="medium",
        category="schedule",
        visibility="company",
    )
    db_session.add(concern)
    db_session.commit()

    concern.acknowledge(user.id)
    concern.start_progress(user.id)
    concern.resolve(user.id, resolution="مصالح رسید")
    assert concern.status == "resolved"
    concern.reopen(user.id, note="دوباره تأخیر")
    assert concern.status == "open"
    concern.escalate(user.id, note="ارجاع")
    assert concern.status == "escalated"
    assert concern.priority == "critical"


def test_create_concern_http(client, db_session):
    company = Company(name="HTTP Concern Co")
    db_session.add(company)
    db_session.flush()
    admin = _user(db_session, "c_admin", "company_admin", company.id)
    project = Project(
        company_id=company.id,
        project_code="PRJ-C1",
        project_name="Concern Project",
        industry="construction",
        base_currency="IRR",
        status="active",
    )
    db_session.add(project)
    db_session.commit()

    client.post("/login", data={"email": admin.email, "password": "pass1234"})
    response = client.post(
        "/concerns/new",
        data={
            "title": "کمبود جرثقیل",
            "description": "نیاز به جرثقیل ۲۵ تن",
            "project_id": str(project.id),
            "category": "resource",
            "priority": "high",
            "visibility": "project",
            "assignee_id": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)
    found = Concern.query.filter_by(title="کمبود جرثقیل").first()
    assert found is not None
    assert found.company_id == company.id
    assert found.project_id == project.id
