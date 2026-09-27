from types import SimpleNamespace
from datetime import date
from decimal import Decimal

from pms_app.utils.evm import calculate_item_evm, aggregate_evm, generate_s_curve
from pms_app.utils.progress import summarize_items


def test_evm_core_metrics_are_consistent():
    r = calculate_item_evm(
        bac=1000,
        progress_percent=40,
        actual_cost=500,
        planned_progress_percent=50,
    )
    assert r.bac == Decimal("1000")
    assert r.ev == Decimal("400.00")
    assert r.ac == Decimal("500")
    assert r.pv == Decimal("500.00")
    assert r.cv == Decimal("-100.00")
    assert r.sv == Decimal("-100.00")
    assert r.cpi == Decimal("0.8000")
    assert r.spi == Decimal("0.8000")
    assert r.eac == Decimal("1250.00")
    assert r.etc == Decimal("750.00")
    assert r.vac == Decimal("-250.00")
    assert r.tcpi == Decimal("1.2000")


def test_evm_clamps_progress_and_never_produces_negative_ev():
    r = calculate_item_evm(bac=1000, progress_percent=150, actual_cost=100)
    assert r.percent_complete == Decimal("100")
    assert r.ev == Decimal("1000.00")

    r = calculate_item_evm(bac=1000, progress_percent=-20, actual_cost=0)
    assert r.percent_complete == Decimal("0")
    assert r.ev == Decimal("0.00")
    assert r.cv == Decimal("0.00")


def test_evm_without_planned_value_does_not_fake_spi():
    r = calculate_item_evm(bac=1000, progress_percent=50, actual_cost=200)
    assert r.pv is None
    assert r.spi is None
    assert r.sv is None


def test_aggregate_evm_uses_totals_for_indexes():
    a = calculate_item_evm(bac=1000, progress_percent=50, actual_cost=400, planned_progress_percent=40)
    b = calculate_item_evm(bac=3000, progress_percent=20, actual_cost=1200, planned_progress_percent=30)
    r = aggregate_evm([a, b])
    assert r.bac == Decimal("4000")
    assert r.ev == Decimal("1100.00")
    assert r.ac == Decimal("1600")
    assert r.pv == Decimal("1300.00")
    assert r.cpi == Decimal("0.6875")
    assert r.spi == Decimal("0.8462")


def test_progress_summary_uses_computed_bac_like_evm():
    item = SimpleNamespace(
        bac=2000,
        adjusted_amount=1000,
        original_amount=500,
        actual_progress_percentage=50,
        actual_cost=800,
        discipline="civil",
    )
    summary = summarize_items([item])
    assert summary["bac_total"] == 2000.0
    assert summary["ev_total"] == 1000.0
    assert summary["overall_pct"] == 50.0


def test_s_curve_does_not_fabricate_planned_value_without_baseline():
    project = SimpleNamespace(
        start_date=date(2026, 1, 1), finish_date=date(2026, 12, 31),
        baseline_start_date=None, baseline_finish_date=None,
        data_date=date(2026, 6, 30),
        contracts=[SimpleNamespace(items=[SimpleNamespace(
            bac=1000, adjusted_amount=1000, original_amount=1000,
            actual_progress_percentage=40, actual_cost=400,
            baseline_start_date=None, baseline_end_date=None,
            actual_start_date=date(2026, 2, 1),
        )])],
    )
    curve = generate_s_curve(project, jalali_labels=False)
    assert curve.baseline_valid is False
    assert curve.labels
    assert curve.pv == [None] * len(curve.labels)
    assert any(v > 0 for v in curve.ev)


def test_s_curve_accepts_valid_project_baseline():
    project = SimpleNamespace(
        start_date=date(2026, 1, 1), finish_date=date(2026, 12, 31),
        baseline_start_date=date(2026, 1, 1), baseline_finish_date=date(2026, 12, 31),
        data_date=date(2026, 6, 30),
        contracts=[SimpleNamespace(items=[SimpleNamespace(
            bac=1000, adjusted_amount=1000, original_amount=1000,
            actual_progress_percentage=40, actual_cost=400,
            baseline_start_date=None, baseline_end_date=None,
            actual_start_date=date(2026, 2, 1),
        )])],
    )
    curve = generate_s_curve(project, jalali_labels=False)
    assert curve.baseline_valid is True
    assert any(v is not None and v > 0 for v in curve.pv)


def test_s_curve_accepts_valid_item_baselines_without_project_baseline():
    project = SimpleNamespace(
        start_date=date(2026, 1, 1), finish_date=date(2026, 12, 31),
        baseline_start_date=None, baseline_finish_date=None,
        data_date=date(2026, 6, 30),
        contracts=[SimpleNamespace(items=[SimpleNamespace(
            bac=1000, adjusted_amount=1000, original_amount=1000,
            actual_progress_percentage=40, actual_cost=400,
            baseline_start_date=date(2026, 1, 1), baseline_end_date=date(2026, 12, 31),
            actual_start_date=date(2026, 2, 1),
        )])],
    )
    curve = generate_s_curve(project, jalali_labels=False)
    assert curve.baseline_valid is True
    assert any(v is not None and v > 0 for v in curve.pv)
