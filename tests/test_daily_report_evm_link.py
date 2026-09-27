from datetime import date
from types import SimpleNamespace

from pms_app.models import Company, Contract, ContractItem, DailyReport, Project
from pms_app.utils.evm import project_evm

def test_submitted_daily_report_does_not_change_item_progress(db_session):
    company = Company(name="EVM Company")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-1", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C1", title="C1")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I1", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=10,
                        actual_cost=100)
    db_session.add_all([project, contract, item])
    db_session.flush()
    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 60, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()
    assert float(item.actual_progress_percentage) == 10.0
    assert float(project_evm(project).ev) == 100.0

def test_final_report_progress_changes_evm(db_session):
    company = Company(name="EVM Company 2")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-2", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C2", title="C2")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I2", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=10,
                        actual_cost=100)
    db_session.add_all([project, contract, item])
    db_session.flush()
    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 60, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()
    report.approve(2, comment="ok", apply_progress=True)
    db_session.flush()
    assert report.progress_applied is True
    assert float(item.actual_progress_percentage) == 60.0
    assert float(project_evm(project).ev) == 600.0


def test_approved_daily_report_cannot_regress_progress(db_session):
    company = Company(name="EVM Company 3")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-3", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C3", title="C3")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I3", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=60,
                        actual_cost=600)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 40, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()
    report.approve(2, comment="stale report", apply_progress=True)
    db_session.flush()

    assert float(item.actual_progress_percentage) == 60.0
    assert float(project_evm(project).ev) == 600.0


def test_daily_report_progress_is_clamped_to_zero_and_hundred(db_session):
    company = Company(name="EVM Company 4")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-4", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C4", title="C4")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I4", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=0,
                        actual_cost=100)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 150, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()
    report.approve(2, comment="clamp", apply_progress=True)
    db_session.flush()

    assert float(item.actual_progress_percentage) == 100.0


def test_daily_report_cannot_be_approved_twice(db_session):
    company = Company(name="EVM Company 5")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-5", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C5", title="C5")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I5", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=20,
                        actual_cost=200)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 70, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()

    report.approve(2, comment="first approval", apply_progress=True)
    db_session.flush()
    assert float(item.actual_progress_percentage) == 70.0
    assert report.progress_applied is True

    try:
        report.approve(2, comment="second approval", apply_progress=True)
    except ValueError:
        pass
    else:
        raise AssertionError("An approved Daily Report must not be approved twice")

    assert float(item.actual_progress_percentage) == 70.0


def test_approved_report_without_progress_application_is_explicit(db_session):
    company = Company(name="EVM Company 6")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-6", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C6", title="C6")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I6", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=20,
                        actual_cost=200)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 80, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()

    assert report.progress_application_status == "pending"
    report.approve(2, comment="approved for record only", apply_progress=False)
    db_session.flush()

    assert report.status == "approved"
    assert report.progress_applied is False
    assert report.progress_application_status == "approved_not_applied"
    assert float(item.actual_progress_percentage) == 20.0
    assert float(project_evm(project).ev) == 200.0


def test_approved_report_progress_can_be_applied_later(db_session):
    company = Company(name="EVM Company 7")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-7", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C7", title="C7")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I7", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=20,
                        actual_cost=200)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 80, "structure_tag": "ST-01"}])
    db_session.add(report)
    db_session.flush()
    report.approve(2, comment="record only", apply_progress=False)
    db_session.flush()

    assert float(item.actual_progress_percentage) == 20.0
    assert report.progress_application_status == "approved_not_applied"

    report.apply_approved_progress()
    db_session.flush()

    assert report.progress_applied is True
    assert report.progress_application_status == "applied"
    assert float(item.actual_progress_percentage) == 80.0
    assert float(project_evm(project).ev) == 800.0


def test_apply_approved_progress_requires_approved_status(db_session):
    company = Company(name="EVM Company 8")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-8", project_name="EVM", status="active")
    report = DailyReport(company_id=company.id, project_id=project.id, submitted_by_id=1,
                         report_date=date.today(), status="submitted",
                         progress_updates=[])
    db_session.add_all([project, report])
    db_session.flush()

    try:
        report.apply_approved_progress()
    except ValueError:
        pass
    else:
        raise AssertionError("Unapproved report must not apply progress")


def test_daily_report_progress_batch_is_atomic_on_invalid_item(db_session):
    company = Company(name="EVM Company 9")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-9", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C9", title="C9")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I9", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=20)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(
        company_id=company.id, project_id=project.id, submitted_by_id=1,
        report_date=date.today(), status="submitted",
        progress_updates=[
            {"contract_item_id": item.id, "progress_percent": 80, "structure_tag": "ST-01"},
            {"contract_item_id": "not-an-id", "progress_percent": 90},
        ],
    )
    db_session.add(report)
    db_session.flush()

    try:
        report.approve(2, comment="invalid batch", apply_progress=True)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid Progress batch must be rejected")

    assert float(item.actual_progress_percentage) == 20.0
    assert report.status == "approved"
    assert report.progress_applied is False


def test_daily_report_progress_rejects_duplicate_item_ids(db_session):
    company = Company(name="EVM Company 10")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-10", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C10", title="C10")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I10", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=20)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(
        company_id=company.id, project_id=project.id, submitted_by_id=1,
        report_date=date.today(), status="submitted",
        progress_updates=[
            {"contract_item_id": item.id, "progress_percent": 40, "structure_tag": "ST-01"},
            {"contract_item_id": item.id, "progress_percent": 60, "structure_tag": "ST-01"},
        ],
    )
    db_session.add(report)
    db_session.flush()

    try:
        report.approve(2, comment="duplicate", apply_progress=True)
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate Progress item IDs must be rejected")

    assert float(item.actual_progress_percentage) == 20.0
    assert report.progress_applied is False


def test_daily_report_progress_rejects_invalid_quantity(db_session):
    company = Company(name="EVM Company 11")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-11", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="C11", title="C11")
    item = ContractItem(contract=contract, company_id=company.id, item_code="I11", description="Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=20,
                        actual_quantity=10)
    db_session.add_all([project, contract, item])
    db_session.flush()

    report = DailyReport(
        company_id=company.id, project_id=project.id, submitted_by_id=1,
        report_date=date.today(), status="submitted",
        progress_updates=[{"contract_item_id": item.id, "progress_percent": 50, "quantity_done": -5, "structure_tag": "ST-01"}],
    )
    db_session.add(report)
    db_session.flush()

    try:
        report.approve(2, comment="invalid quantity", apply_progress=True)
    except ValueError:
        pass
    else:
        raise AssertionError("Negative quantity must be rejected")

    assert float(item.actual_progress_percentage) == 20.0
    assert float(item.actual_quantity) == 10.0
    assert report.progress_applied is False


def test_daily_report_progress_requires_location_or_structure_tag(db_session):
    company = Company(name="EVM Location Company")
    db_session.add(company)
    db_session.flush()
    project = Project(company_id=company.id, project_code="EVM-LOC", project_name="EVM", status="active")
    contract = Contract(project_id=project.id, company_id=company.id, contract_number="CL", title="CL")
    item = ContractItem(contract=contract, company_id=company.id, item_code="IL", description="Tagged Work",
                        original_amount=1000, adjusted_amount=1000, actual_progress_percentage=10)
    db_session.add_all([project, contract, item])
    db_session.flush()
    report = DailyReport(
        company_id=company.id, project_id=project.id, submitted_by_id=1,
        report_date=date.today(), status="submitted",
        progress_updates=[{"contract_item_id": item.id, "progress_percent": 50}],
    )
    db_session.add(report)
    db_session.flush()
    try:
        report.approve(2, comment="missing reference", apply_progress=True)
    except ValueError as exc:
        assert "لوکیشن" in str(exc) or "تگ سازه" in str(exc)
    else:
        raise AssertionError("Progress must identify a location or structure tag")
    assert float(item.actual_progress_percentage) == 10.0
    assert report.progress_applied is False
