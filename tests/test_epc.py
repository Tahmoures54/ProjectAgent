# tests/test_epc.py
from pms_app.utils.epc import classify_epc_phase, summarize_epc_phases
from pms_app.utils.progress import summarize_items


class _Item:
    def __init__(self, **kwargs):
        self.title = kwargs.get("title", "")
        self.phase = kwargs.get("phase")
        self.l3_phase = kwargs.get("l3_phase")
        self.discipline = kwargs.get("discipline")
        self.l4_discipline = kwargs.get("l4_discipline")
        self.work_package = kwargs.get("work_package")
        self.l8_work_package = None
        self.cost_category = kwargs.get("cost_category")
        self.wbs_code = kwargs.get("wbs_code")
        self.cbs_code = None
        self.l9_activity_name = None
        self.adjusted_amount = kwargs.get("bac", 100)
        self.original_amount = kwargs.get("bac", 100)
        self.actual_progress_percentage = kwargs.get("pct", 0)
        self.actual_cost = kwargs.get("ac", 0)
        self.epc_phase = kwargs.get("epc_phase")


def test_classify_epc_phase_keywords():
    assert classify_epc_phase(_Item(title="تهیه IFC نقشه‌های piping")) == "engineering"
    assert classify_epc_phase(_Item(title="خرید فلنج و صدور PO")) == "procurement"
    assert classify_epc_phase(_Item(title="نصب پمپ و بتن‌ریزی فونداسیون")) == "construction"
    assert classify_epc_phase(_Item(title="سایر"), explicit="E") == "engineering"


def test_summarize_epc_and_progress_phases():
    items = [
        _Item(title="طراحی P&ID", bac=200, pct=50),
        _Item(title="سفارش خرید تجهیزات", bac=100, pct=20),
        _Item(title="نصب مکانیکال", bac=100, pct=80),
    ]
    epc = summarize_epc_phases(items)
    by_key = epc["by_key"]
    assert by_key["engineering"]["item_count"] == 1
    assert by_key["procurement"]["item_count"] == 1
    assert by_key["construction"]["item_count"] == 1
    summary = summarize_items(items)
    assert summary["overall_pct"] > 0
    keys = {p["key"] for p in summary["phases"]}
    assert {"engineering", "procurement", "construction"} <= keys
