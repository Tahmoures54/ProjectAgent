from __future__ import annotations

from datetime import date

from pms_app.models import ActionItem
from pms_app.models.project_membership import ProjectMembership
from tests.test_access import _company_project_contract, _login, _user


def test_action_plan_isolated_across_companies(client, db_session):
    company_a, project_a, _, _ = _company_project_contract(db_session, "ACT-A")
    company_b, project_b, _, _ = _company_project_contract(db_session, "ACT-B")

    admin_a = _user(db_session, "action_a", "company_admin", company_a.id)
    admin_b = _user(db_session, "action_b", "company_admin", company_b.id)

    action = ActionItem(
        company_id=company_a.id,
        project_id=project_a.id,
        title="Secret action A",
        status="open",
        priority="high",
        due_date=date.today(),
        created_by_id=admin_a.id,
    )
    db_session.add(action)
    db_session.commit()

    _login(client, admin_b.email)

    # A tenant must not discover another tenant's action through a project URL.
    assert client.get(f"/projects/{project_a.id}/actions").status_code in (403, 404)
    assert client.get(f"/projects/{project_a.id}/actions/{action.id}/edit").status_code in (403, 404)

    # Mutating endpoints must be protected by the same project boundary.
    done = client.post(f"/projects/{project_a.id}/actions/{action.id}/done")
    assert done.status_code in (403, 404)
    delete = client.post(f"/projects/{project_a.id}/actions/{action.id}/delete")
    assert delete.status_code in (403, 404)

    db_session.refresh(action)
    assert action.status == "open"
    assert db_session.get(ActionItem, action.id) is not None


def test_action_plan_membership_is_project_specific(client, db_session):
    company, project_a, _, _ = _company_project_contract(db_session, "ACT-M")
    project_b = _company_project_contract(db_session, "ACT-N")[1]

    member = _user(db_session, "action_member", "company_user", company.id)
    db_session.add(
        ProjectMembership(
            project_id=project_a.id,
            user_id=member.id,
            role="member",
            status="active",
        )
    )
    db_session.commit()

    _login(client, member.email)

    assert client.get(f"/projects/{project_a.id}/actions").status_code == 200
    assert client.get(f"/projects/{project_b.id}/actions").status_code in (403, 404)
