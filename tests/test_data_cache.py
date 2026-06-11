"""เทส cache resilience — _refresh_all รายงานสถานะ fetch ถูกต้อง
และ logic retry เร็วเมื่อ Power BI ล้มเหลว."""
import data_cache as dc


def _ok_row():
    return {
        'YW': '202610', 'MC_GROUP': 'A', 'ITEM_CODE': 'X', 'KP_Weight': 1,
        'Master.MC': 'A', 'Master.Guage': '7', 'Totals_MC': 1,
        'MC_Used_Normal': 0, 'MC_Used_FQC': 0, 'MachineUsed': 1,
        'KNIT_SALE_NAME': 'somchai',
    }


def _patch_ok(monkeypatch):
    monkeypatch.setattr(dc, "_pbi_fetch_table", lambda name: {'data': [_ok_row()]})
    monkeypatch.setattr(dc, "_pbi_fetch_dax", lambda q: {'data': [{'YW': '202610', 'Master.MC': 'A', 'KG_Ava': 5}]})


def test_refresh_all_returns_true_when_all_fetches_succeed(monkeypatch):
    _patch_ok(monkeypatch)
    cache = dc.DataCache()
    assert cache._refresh_all() is True
    assert cache.is_ready('query_booking') is True


def test_refresh_all_returns_false_when_table_fetch_fails(monkeypatch):
    def fetch(name):
        if name == dc._TABLE_BOOKING:
            raise ConnectionError("power bi timeout")
        return {'data': [_ok_row()]}
    monkeypatch.setattr(dc, "_pbi_fetch_table", fetch)
    monkeypatch.setattr(dc, "_pbi_fetch_dax", lambda q: {'data': []})
    cache = dc.DataCache()
    assert cache._refresh_all() is False


def test_refresh_all_returns_false_when_dax_fails(monkeypatch):
    monkeypatch.setattr(dc, "_pbi_fetch_table", lambda name: {'data': [_ok_row()]})
    def fail_dax(q):
        raise ConnectionError("dax error")
    monkeypatch.setattr(dc, "_pbi_fetch_dax", fail_dax)
    cache = dc.DataCache()
    assert cache._refresh_all() is False


# --- logic การตัดสินใจ retry (เลียนแบบ branch ใน _run โดยไม่รัน loop จริง) ---
def _decide(ok: bool, retries: int):
    if not ok and retries < dc._MAX_QUICK_RETRIES:
        return True, retries + 1
    return False, 0


def test_quick_retry_budget_then_fallback_to_schedule():
    r = 0
    decisions = []
    for _ in range(dc._MAX_QUICK_RETRIES + 1):
        quick, r = _decide(False, r)
        decisions.append(quick)
    # quick retry ครบ N ครั้งแล้วครั้งถัดไปกลับไปรอ schedule ปกติ
    assert decisions == [True] * dc._MAX_QUICK_RETRIES + [False]


def test_success_resets_retry_counter():
    quick, r = _decide(True, 2)
    assert quick is False
    assert r == 0


def test_aggregate_sales_includes_per_week_breakdown():
    rows = [
        {'YW': '202610', 'ITEM_CODE': 'X', 'KP_Weight': 100, 'KNIT_SALE_NAME': 'somchai'},
        {'YW': '202611', 'ITEM_CODE': 'Y', 'KP_Weight': 50, 'KNIT_SALE_NAME': 'somchai'},
    ]
    result = dc._aggregate_sales(rows)
    s = result['somchai']
    assert s['kg'] == 150.0
    assert s['kg_yw'] == {'202610': 100.0, '202611': 50.0}


def test_refresh_all_stores_table_item_columns(monkeypatch):
    _patch_ok(monkeypatch)
    cache = dc.DataCache()
    cache._refresh_all()
    assert 'YW' in cache.get_status()['table_item_columns']
