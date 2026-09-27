# tests/test_daily_reports.py
from __future__ import annotations

from datetime import date, timedelta, timedelta

from pms_app.models import Company, Contract, ContractItem, DailyReport, DailyReportProgress, Project, Role, User
from pms_app.models.project_membership import ProjectMembership


def _role(session, name):
    return Role.query.filter_by(name=name).first()


def _user(session, prefix, role_name, company_id=None, password="pass1234"):
    user = User(
        email=f"{prefix}@example.com",
        full_name=prefix,
        is_active=True,
        company_id=company_id,
    )
    user.set_password(password)
    role = _role(session, role_name)
    if role:
        user.roles = [role]
    session.add(user)
    session.commit()
    return user


def _company_project(session, suffix="DR"):
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
        finish_date=date.today() - timedelta(days=3),
    )
    session.add(project)
    session.commit()
    return company, project


def _login(client, email, password="pass1234"):
    return client.post("/login", data={"email": email, "password": password})


def test_daily_reports_list_requires_login(client):
    response = client.get("/daily-reports/")
    assert response.status_code in (302, 401)


def test_daily_report_model_workflow_and_progress(db_session):
    company, project = _company_project(db_session, "WF")
    admin = _user(db_session, "dr_admin", "company_admin", company.id)
    worker = _user(db_session, "dr_worker", "contractor", company.id)

    contract = Contract(
        company_id=company.id,
        project_id=project.id,
        contract_number="CNT-DR",
        contract_title="Main",
        contract_type="EPC",
        pricing_model="lumpsum",
        currency="IRR",
        status="active",
    )
    db_session.add(contract)
    db_session.flush()
    item = ContractItem(
        company_id=company.id,
        contract_id=contract.id,
        title="Foundation",
        status="open",
        actual_progress_percentage=10,
        original_amount=1000,
        adjusted_amount=1000,
    )
    db_session.add(item)
    db_session.commit()

    report = DailyReport(
        company_id=company.id,
        project_id=project.id,
        report_date=date.today(),
        submitted_by_id=worker.id,
        work_performed="بتن‌ریزی فونداسیون",
        progress_updates=[{"contract_item_id": item.id, "progress_percent": 40, "location": "Unit-3 / Grid A4"}],
        status="draft",
    )
    db_session.add(report)
    db_session.commit()

    report.submit(worker.id)
    assert report.status == "submitted"
    report.approve(admin.id, comment="تأیید", apply_progress=True)
    db_session.commit()

    assert report.status == "approved"
    assert report.progress_applied is True
    assert float(item.actual_progress_percentage) == 40.0


def test_contractor_submits_and_admin_approves_via_http(client, db_session):
    company, project = _company_project(db_session, "HTTP")
    admin = _user(db_session, "http_admin", "company_admin", company.id)
    worker = _user(db_session, "http_worker", "contractor", company.id)
    db_session.add(
        ProjectMembership(
            project_id=project.id,
            user_id=worker.id,
            role="contractor",
            status="active",
        )
    )
    db_session.commit()

    _login(client, worker.email)
    create = client.post(
        f"/daily-reports/project/{project.id}/new",
        data={
            "report_date": date.today().isoformat(),
            "work_performed": "نصب اسکلت",
            "manpower_total": "8",
            "action": "submit",
        },
        follow_redirects=False,
    )
    assert create.status_code in (301, 302)
    report = DailyReport.query.filter_by(project_id=project.id).first()
    assert report is not None
    assert report.status == "submitted"

    client.get("/logout")
    _login(client, admin.email)
    review = client.post(
        f"/daily-reports/{report.id}/review",
        data={"action": "approve", "comment": "ok", "apply_progress": "yes"},
        follow_redirects=False,
    )
    assert review.status_code in (301, 302)
    db_session.refresh(report)
    assert report.status == "approved"


def test_daily_report_excel_template_and_import(client, db_session):
    from io import BytesIO

    from openpyxl import Workbook, load_workbook

    company, project = _company_project(db_session, "XLS")
    admin = _user(db_session, "xls_admin", "company_admin", company.id)
    db_session.add(
        ProjectMembership(
            project_id=project.id,
            user_id=admin.id,
            role="admin",
            status="active",
        )
    )
    db_session.commit()
    _login(client, admin.email)

    template = client.get(f"/daily-reports/project/{project.id}/template.xlsx")
    assert template.status_code == 200
    assert "spreadsheetml" in template.content_type
    wb = load_workbook(BytesIO(template.data))
    assert "گزارش روزانه" in wb.sheetnames
    assert "مهندسی" in wb.sheetnames
    progress_ws = wb["پیشرفت"]
    assert list(progress_ws.iter_rows(min_row=1, max_row=1, values_only=True))[0] == ["تاریخ", "شناسه آیتم", "کد WBS", "درصد پیشرفت", "مقدار انجام‌شده", "لوکیشن", "تگ سازه", "یادداشت"]

    out = Workbook()
    ws = out.active
    ws.title = "گزارش روزانه"
    ws.append(["تاریخ", "شرح کار", "نیروی انسانی", "فاز EPC", "هوا"])
    ws.append([date.today().isoformat(), "لوله کشی واحد ۳", 15, "اجرا", "آفتابی"])
    mp = out.create_sheet("نیروی انسانی")
    mp.append(["تاریخ", "نقش", "تعداد"])
    mp.append([date.today().isoformat(), "جوشکار", 5])
    progress = out.create_sheet("پیشرفت")
    progress.append(["تاریخ", "شناسه آیتم", "کد WBS", "درصد پیشرفت", "مقدار انجام‌شده", "لوکیشن", "تگ سازه", "یادداشت"])
    progress.append([date.today().isoformat(), "", "1.2.3", 35, 12, "Unit-3 / Grid A4", "ST-01", "فونداسیون"])
    eng = out.create_sheet("مهندسی")
    eng.append(["تاریخ", "شماره مدرک", "عنوان", "وضعیت"])
    eng.append([date.today().isoformat(), "PID-003", "P&ID واحد ۳", "IFC"])
    bio = BytesIO()
    out.save(bio)
    bio.seek(0)

    uploaded = client.post(
        f"/daily-reports/project/{project.id}/import",
        data={"file": (bio, "daily.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert uploaded.status_code in (301, 302)
    report = DailyReport.query.filter_by(project_id=project.id).first()
    assert report is not None
    assert report.status == "draft"
    assert report.work_performed == "لوله کشی واحد ۳"
    assert report.manpower_total == 15
    assert report.epc_phase == "construction"
    assert report.manpower_details and report.manpower_details[0]["role"] == "جوشکار"
    assert report.engineering_outputs and report.engineering_outputs[0]["doc_no"] == "PID-003"
    assert report.progress_updates and report.progress_updates[0]["location"] == "Unit-3 / Grid A4"
    assert report.progress_updates[0]["structure_tag"] == "ST-01"

    exported = client.get(f"/daily-reports/project/{project.id}/export.xlsx")
    assert exported.status_code == 200
    assert "spreadsheetml" in exported.content_type


def test_epc_controls_page(client, db_session):
    company, project = _company_project(db_session, "EPC")
    admin = _user(db_session, "epc_admin", "company_admin", company.id)
    db_session.add(
        ProjectMembership(
            project_id=project.id,
            user_id=admin.id,
            role="admin",
            status="active",
        )
    )
    db_session.commit()
    _login(client, admin.email)
    page = client.get(f"/projects/{project.id}/epc")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "اتاق کنترل" in html
    assert "مهندسی" in html


def test_approved_report_apply_progress_ui_and_http_action(client, db_session):
    import re

    company, project = _company_project(db_session, "APPLYUI")
    admin = _user(db_session, "apply_ui_admin", "company_admin", company.id)
    worker = _user(db_session, "apply_ui_worker", "contractor", company.id)

    contract = Contract(
        company_id=company.id,
        project_id=project.id,
        contract_number="CNT-APPLYUI",
        contract_title="Main",
        contract_type="EPC",
        pricing_model="lumpsum",
        currency="IRR",
        status="active",
    )
    db_session.add(contract)
    db_session.flush()
    item = ContractItem(
        company_id=company.id,
        contract_id=contract.id,
        title="Civil Works",
        status="open",
        actual_progress_percentage=10,
        original_amount=1000,
        adjusted_amount=1000,
    )
    db_session.add(item)
    db_session.flush()

    report = DailyReport(
        company_id=company.id,
        project_id=project.id,
        report_date=date.today(),
        submitted_by_id=worker.id,
        progress_updates=[{"contract_item_id": item.id, "progress_percent": 60, "structure_tag": "TK-101"}],
        status="approved",
        progress_applied=False,
    )
    db_session.add(report)
    db_session.commit()

    _login(client, admin.email)
    detail = client.get(f"/daily-reports/{report.id}")
    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "پیشرفت این گزارش هنوز روی آیتم‌ها اعمال نشده است" in html
    assert f'/daily-reports/{report.id}/apply-progress' in html
    assert "اعمال پیشرفت" in html

    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert token is not None

    response = client.post(
        f"/daily-reports/{report.id}/apply-progress",
        data={"csrf_token": token.group(1)},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)

    db_session.refresh(report)
    db_session.refresh(item)
    assert report.progress_applied is True
    assert report.progress_application_status == "applied"
    assert float(item.actual_progress_percentage) == 60.0


def test_apply_progress_endpoint_rejects_unapproved_report(client, db_session):
    company, project = _company_project(db_session, "APPLYNO")
    admin = _user(db_session, "apply_no_admin", "company_admin", company.id)
    worker = _user(db_session, "apply_no_worker", "contractor", company.id)

    report = DailyReport(
        company_id=company.id,
        project_id=project.id,
        report_date=date.today(),
        submitted_by_id=worker.id,
        progress_updates=[],
        status="submitted",
        progress_applied=False,
    )
    db_session.add(report)
    db_session.commit()

    _login(client, admin.email)
    response = client.post(
        f"/daily-reports/{report.id}/apply-progress",
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)
    db_session.refresh(report)
    assert report.status == "submitted"
    assert report.progress_applied is False



def test_progress_traceability_excel_export_preserves_filters_and_scope(client, db_session):
    from io import BytesIO
    from openpyxl import load_workbook

    company, project = _company_project(db_session, "TRACE")
    admin = _user(db_session, "trace_admin", "company_admin", company.id)
    other_company, other_project = _company_project(db_session, "TRACEOTHER")
    _user(db_session, "trace_other", "company_admin", other_company.id)

    contract = Contract(
        company_id=company.id,
        project_id=project.id,
        contract_number="CNT-TRACE",
        contract_title="Trace",
        contract_type="EPC",
        pricing_model="lumpsum",
        currency="IRR",
        status="active",
    )
    db_session.add(contract)
    db_session.flush()
    item = ContractItem(
        company_id=company.id,
        contract_id=contract.id,
        title="Pipe Rack",
        wbs_code="1.2.3",
        status="open",
        actual_progress_percentage=40,
        original_amount=1000,
        adjusted_amount=1000,
    )
    db_session.add(item)
    db_session.flush()

    report = DailyReport(
        company_id=company.id,
        project_id=project.id,
        report_date=date.today(),
        submitted_by_id=admin.id,
        status="approved",
        progress_applied=True,
        progress_updates=[{"contract_item_id": item.id, "progress_percent": 40, "quantity_done": 12,
                           "location": "Unit-3 / Grid A4", "structure_tag": "ST-01", "notes": "Foundation"}],
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(DailyReportProgress(
        report_id=report.id,
        contract_item_id=item.id,
        company_id=company.id,
        project_id=project.id,
        location="Unit-3 / Grid A4",
        structure_tag="ST-01",
        progress_percent=40,
        quantity_done=12,
        notes="Foundation",
        applied_by_id=admin.id,
    ))
    db_session.add(DailyReportProgress(
        report_id=report.id,
        contract_item_id=item.id,
        company_id=company.id,
        project_id=project.id,
        location="Unit-4 / Grid B2",
        structure_tag="ST-02",
        progress_percent=45,
        quantity_done=15,
        notes="Other location",
        applied_by_id=admin.id,
    ))
    other_report = DailyReport(
        company_id=other_company.id,
        project_id=other_project.id,
        report_date=date.today(),
        submitted_by_id=admin.id,
        status="approved",
        progress_applied=True,
    )
    db_session.add(other_report)
    db_session.commit()

    _login(client, admin.email)
    response = client.get(
        f"/daily-reports/progress-traceability/export.xlsx"
        f"?project_id={project.id}&structure_tag=ST-01"
    )
    assert response.status_code == 200
    assert "spreadsheetml" in response.content_type

    wb = load_workbook(BytesIO(response.data), read_only=True)
    ws = wb["Progress Traceability"]
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == (
        "تاریخ", "پروژه", "شناسه آیتم", "کد WBS", "عنوان آیتم",
        "لوکیشن", "تگ سازه", "درصد پیشرفت", "مقدار انجام‌شده",
        "اعمال‌کننده", "زمان ثبت", "یادداشت",
        "تغییر نسبت به ثبت قبل", "وضعیت کنترل کیفیت",
    )
    assert len(rows) == 2
    assert rows[1][1] == project.project_name
    assert rows[1][3] == "1.2.3"
    assert rows[1][5] == "Unit-3 / Grid A4"
    assert rows[1][6] == "ST-01"
    assert rows[1][11] == "Foundation"
    assert rows[1][12] == ""
    assert rows[1][13] == "اولین ثبت"

    # A second record verifies delta/quality classification.
    report2 = DailyReport(
        company_id=company.id,
        project_id=project.id,
        report_date=date.today(),
        submitted_by_id=admin.id,
        status="approved",
        progress_applied=True,
        progress_updates=[],
    )
    db_session.add(report2)
    db_session.flush()
    db_session.add(DailyReportProgress(
        report_id=report2.id,
        contract_item_id=item.id,
        company_id=company.id,
        project_id=project.id,
        location="Unit-3 / Grid A4",
        structure_tag="ST-01",
        progress_percent=55,
        quantity_done=18,
        notes="Steel",
        applied_by_id=admin.id,
        created_at=report.created_at + timedelta(minutes=1),
    ))
    db_session.commit()

    response = client.get(
        f"/daily-reports/progress-traceability/export.xlsx"
        f"?project_id={project.id}&structure_tag=ST-01"
    )
    assert response.status_code == 200
    wb2 = load_workbook(BytesIO(response.data), read_only=True)
    rows2 = list(wb2["Progress Traceability"].iter_rows(values_only=True))
    assert len(rows2) == 3
    assert rows2[1][12] == 15
    assert rows2[1][13] == "افزایش"
