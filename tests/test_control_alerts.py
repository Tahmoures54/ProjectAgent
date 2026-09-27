from __future__ import annotations

from datetime import date, datetime, timedelta

from pms_app.models import Company, Contract, ContractItem, DailyReport, DailyReportProgress, Project, Role, User


def _role(name):
    return Role.query.filter_by(name=name).first()


def _login(client, email, password="pass1234"):
    return client.post("/login", data={"email": email, "password": password})


def test_control_alerts_detects_progress_anomaly_and_stale_data(client, db_session):
    company = Company(name="Alerts Co")
    db_session.add(company)
    db_session.flush()
    project = Project(
        company_id=company.id, project_code="PRJ-ALERT", project_name="Alert Project",
        industry="construction", base_currency="IRR", status="active",
        finish_date=date.today() + timedelta(days=90),
    )
    db_session.add(project)
    db_session.flush()
    user = User(email="alerts@example.com", full_name="Alerts Admin", is_active=True, company_id=company.id)
    user.set_password("pass1234")
    role = _role("company_admin")
    if role:
        user.roles = [role]
    db_session.add(user)
    db_session.flush()
    contract = Contract(
        company_id=company.id, project_id=project.id, contract_number="CNT-A",
        contract_title="Alert Contract", contract_type="EPC", pricing_model="lumpsum",
        currency="IRR", status="active",
    )
    db_session.add(contract)
    db_session.flush()
    item = ContractItem(
        company_id=company.id, contract_id=contract.id, title="Steel Structure",
        wbs_code="1.2.3", status="open", actual_progress_percentage=70,
        original_amount=1000, adjusted_amount=1000,
    )
    db_session.add(item)
    db_session.flush()

    for idx, progress in enumerate((30, 70), start=1):
        report = DailyReport(
            company_id=company.id, project_id=project.id, report_date=date.today(),
            submitted_by_id=user.id, status="approved", progress_applied=True, progress_updates=[],
        )
        db_session.add(report)
        db_session.flush()
        db_session.add(DailyReportProgress(
            report_id=report.id, contract_item_id=item.id, company_id=company.id,
            project_id=project.id, location="Area A / Grid 4", structure_tag="ST-104",
            progress_percent=progress, quantity_done=10, applied_by_id=user.id,
            created_at=datetime.utcnow() - timedelta(days=5 - idx),
        ))
    db_session.commit()

    _login(client, user.email)
    response = client.get(f"/daily-reports/control-alerts?project_id={project.id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Progress غیرعادی" in html
    assert "Progress قدیمی" in html
    assert "ST-104" in html
