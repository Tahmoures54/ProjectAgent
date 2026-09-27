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
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 60}])
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
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 60}])
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
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 40}])
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
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 150}])
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
                         progress_updates=[{"contract_item_id": item.id, "progress_percent": 70}])
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
