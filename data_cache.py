import logging
import os
import threading
import time
from datetime import datetime, timedelta
from datetime import time as dt_time
from typing import Dict, Optional, Tuple

from collections import defaultdict

from dotenv import load_dotenv
from powerbi_connector import fetch_table as _pbi_fetch_table, fetch_dax as _pbi_fetch_dax

load_dotenv()

logger = logging.getLogger(__name__)

REFRESH_HOURS = (5, 12, 20)  # 05:00, 12:00, 20:00
_RETRY_SECS = 300         # หน่วงก่อน retry เมื่อ refresh ดึง Power BI ล้มเหลว (5 นาที)
_MAX_QUICK_RETRIES = 3    # จำนวน retry เร็วก่อนกลับไปรอ schedule ปกติ

_TABLE_BOOKING = os.getenv('TABLE_NAME', 'BookingMaster')
_TABLE_MC = os.getenv('TABLE_NAME_MC', 'Table_MC')
_TABLE_ITEM = os.getenv('TABLE_NAME_ITEM', 'Table_Item')

# intent key → ข้อมูลที่ต้องใช้
# query_machine / query_cap_ava ใช้ Table_MC + BookingMaster รวมกัน
# query_knit_plan / query_booking ใช้ BookingMaster อย่างเดียว
# query_item ใช้ Table_Item join Table_MC ผ่าน MAP2
DATA_KEYS = [
    'query_machine',
    'query_cap_ava',
    'query_knit_plan',
    'query_booking',
    'query_item',
    'query_sales',
]


_MAX_WEEKS = 52  # จำกัดแค่ 20 สัปดาห์ข้างหน้า


_PAST_WEEKS = 52  # แสดงย้อนหลัง 4 สัปดาห์

def _week_range() -> tuple[str, str]:
    now = datetime.now()
    past = now - timedelta(weeks=_PAST_WEEKS)
    min_yw = f"{past.year}{past.isocalendar()[1]:02d}"
    future = now + timedelta(weeks=_MAX_WEEKS)
    max_yw = f"{future.year}{future.isocalendar()[1]:02d}"
    return min_yw, max_yw


def _aggregate_mc(rows: list) -> str:
    """CSV: YW,Group,Guage,Total,Used_N,Used_F,Ava — ทุก MC ทุก gauge ทุก week ในช่วง"""
    min_yw, max_yw = _week_range()
    groups: dict = defaultdict(lambda: [0.0, 0.0, 0.0])  # Total,Used_N,Used_F
    for r in rows:
        yw = str(r.get('YW', '') or '')
        if not (min_yw <= yw <= max_yw):
            continue
        key = (yw, str(r.get('Master.MC', '') or ''), str(r.get('Master.Guage', '') or ''))
        g = groups[key]
        g[0] += float(r.get('Totals_MC', 0) or 0)
        g[1] += float(r.get('MC_Used_Normal', 0) or 0)
        g[2] += float(r.get('MC_Used_FQC', 0) or 0)

    lines = ['YW,Group,Guage,Total,Used_N,Used_F,Ava']
    for (yw, group, guage), g in sorted(groups.items(), key=lambda x: (x[0][0] or '', x[0][1] or '', x[0][2] or '')):
        ava = round(g[0] - g[1] - g[2], 1)  # Totals_MC - MC_Used_Normal - MC_Used_FQC
        lines.append(f"{yw},{group},{guage},{round(g[0],1)},{round(g[1],1)},{round(g[2],1)},{ava}")
    return '\n'.join(lines)


def _aggregate_item_plan(booking_rows: list) -> str:
    """CSV: Item,Group,KP_Weight,YW — ดึงจาก BookingMaster โดยตรง (มี ITEM_CODE + YW + KP_Weight ต่อ row)"""
    min_yw, max_yw = _week_range()

    lines = ['Item,Group,KP_Weight,YW']
    for r in booking_rows:
        item = str(r.get('ITEM_CODE', '') or '').strip()
        group = str(r.get('MC_GROUP', '') or '').strip() or '(ไม่ระบุกลุ่ม)'
        kp_raw = r.get('KP_Weight')
        yw = str(r.get('YW', '') or '').strip()
        if not item or not yw or not (min_yw <= yw <= max_yw):
            continue
        kp = str(kp_raw) if kp_raw is not None else ''
        lines.append(f"{item},{group},{kp},{yw}")
    return '\n'.join(lines)


_KG_AVA_DAX = """EVALUATE
SUMMARIZECOLUMNS(
    Table_MC[YW],
    Table_MC[Master.MC],
    "KG_Ava", [KG_Ava_Display]
)"""


def _aggregate_kg_ava(rows: list) -> str:
    """CSV: YW,Group,KG_Ava — จาก SUMMARIZECOLUMNS([KG_Ava_Display])"""
    min_yw, max_yw = _week_range()
    lines = ['YW,Group,KG_Ava']
    for r in rows:
        yw = str(r.get('YW', '') or '').strip()
        if not yw or not (min_yw <= yw <= max_yw):
            continue
        group = str(r.get('Master.MC', '') or r.get('MC', '') or '').strip()
        kg_ava = r.get('KG_Ava')
        if kg_ava is None:
            continue
        lines.append(f"{yw},{group},{round(float(kg_ava), 2)}")
    return '\n'.join(lines)


def _aggregate_sales(booking_rows: list) -> dict:
    """Returns {sales_name_lower: {name, item_count, kg}} from BookingMaster KNIT_SALE_NAME column"""
    min_yw, max_yw = _week_range()
    sales_map: dict = {}
    for r in booking_rows:
        yw = str(r.get('YW', '') or '').strip()
        if not (min_yw <= yw <= max_yw):
            continue
        sales_name = str(r.get('KNIT_SALE_NAME', '') or '').strip()
        if not sales_name:
            continue
        item = str(r.get('ITEM_CODE', '') or '').strip()
        kp_raw = r.get('KP_Weight')
        kp = float(kp_raw) if kp_raw is not None else 0.0

        key = sales_name.lower()
        if key not in sales_map:
            sales_map[key] = {'name': sales_name, 'items': set(), 'kg': 0.0}
        if item:
            sales_map[key]['items'].add(item)
        sales_map[key]['kg'] += kp

    result = {k: {'name': v['name'], 'item_count': len(v['items']), 'kg': round(v['kg'], 1)}
              for k, v in sales_map.items()}

    # System-wide total (unique items across all sales)
    all_items: set = set()
    total_kg = 0.0
    for v in sales_map.values():
        all_items.update(v['items'])
        total_kg += v['kg']
    result['__system__'] = {'name': 'ระบบทั้งหมด', 'item_count': len(all_items), 'kg': round(total_kg, 1)}

    return result


def _aggregate_booking(rows: list) -> str:
    """CSV: YW,MC_GROUP,Used — เฉพาะ 20 week ข้างหน้า
    ไม่รวม Diff เพราะ sum(Diff_MC) ข้าม rows ให้ค่าที่ผิด — ใช้ Ava จาก Table_MC แทน"""
    min_yw, max_yw = _week_range()
    groups: dict = defaultdict(float)
    for r in rows:
        yw = str(r.get('YW', '') or '')
        if not (min_yw <= yw <= max_yw):
            continue
        key = (yw, str(r.get('MC_GROUP', '') or ''))
        groups[key] += float(r.get('MachineUsed', 0) or 0)

    lines = ['YW,MC_GROUP,Used']
    for (yw, mc_group), used in sorted(groups.items(), key=lambda x: (x[0][0] or '', x[0][1] or '')):
        lines.append(f"{yw},{mc_group},{round(used,1)}")
    return '\n'.join(lines)


class DataCache:
    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._ready: Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._last_refresh: Optional[datetime] = None
        self._next_refresh: Optional[datetime] = None
        self._row_counts: Dict[str, int] = {}

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name='DataCacheThread')
        self._thread.start()
        logger.info("DataCache: background thread started — loading data from Power BI...")

    def _run(self):
        ok = self._refresh_all()
        retries = 0

        while True:
            if not ok and retries < _MAX_QUICK_RETRIES:
                # refresh รอบล่าสุดมี fetch ที่ล้มเหลว — ลองใหม่เร็วๆ แทนการรอ schedule ถัดไป
                retries += 1
                next_time = datetime.now() + timedelta(seconds=_RETRY_SECS)
                logger.warning(
                    f"DataCache: last refresh had fetch errors — quick retry #{retries}/{_MAX_QUICK_RETRIES} "
                    f"in {_RETRY_SECS}s"
                )
            else:
                if not ok:
                    logger.error(
                        f"DataCache: refresh still failing after {_MAX_QUICK_RETRIES} retries — "
                        f"falling back to normal schedule"
                    )
                retries = 0
                next_time = self._next_refresh_time()
                logger.info(f"DataCache: next refresh at {next_time.strftime('%H:%M')}")

            with self._lock:
                self._next_refresh = next_time
            sleep_secs = max((next_time - datetime.now()).total_seconds(), 0)
            time.sleep(sleep_secs)
            logger.info("DataCache: refresh starting...")
            ok = self._refresh_all()

    def _next_refresh_time(self) -> datetime:
        now = datetime.now()
        today = now.date()
        candidates = [
            datetime.combine(today, dt_time(hour, 0))
            for hour in REFRESH_HOURS
            if datetime.combine(today, dt_time(hour, 0)) > now
        ]
        if not candidates:
            tomorrow = today + timedelta(days=1)
            candidates = [datetime.combine(tomorrow, dt_time(REFRESH_HOURS[0], 0))]
        return min(candidates)

    def _refresh_all(self) -> bool:
        """ดึงข้อมูลทั้งหมดจาก Power BI. คืน True ถ้าทุก fetch สำเร็จ,
        False ถ้ามีอย่างน้อย 1 fetch ล้มเหลว (ให้ caller สั่ง retry เร็วได้)"""
        fetch_failed = False

        # --- ดึง BookingMaster ---
        booking_rows = []
        try:
            result = _pbi_fetch_table(_TABLE_BOOKING)
            booking_rows = result.get('data', [])
            logger.info(f"DataCache: BookingMaster loaded — {len(booking_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to load BookingMaster: {e}")
            fetch_failed = True

        # --- ดึง Table_MC ---
        mc_rows = []
        try:
            result = _pbi_fetch_table(_TABLE_MC)
            mc_rows = result.get('data', [])
            logger.info(f"DataCache: Table_MC loaded — {len(mc_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to load Table_MC: {e}")
            fetch_failed = True

        # --- ดึง Table_Item ---
        item_rows = []
        try:
            result = _pbi_fetch_table(_TABLE_ITEM)
            item_rows = result.get('data', [])
            logger.info(f"DataCache: Table_Item loaded — {len(item_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to load Table_Item: {e}")
            fetch_failed = True

        # --- Aggregate Table_MC: group by YW + Master.MC ---
        mc_summary = _aggregate_mc(mc_rows)

        # --- Aggregate BookingMaster: group by YW + MC_GROUP ---
        booking_summary = _aggregate_booking(booking_rows)

        # --- Item plan จาก BookingMaster โดยตรง (ITEM_CODE + YW + KP_Weight) ---
        item_summary = _aggregate_item_plan(booking_rows)

        # --- Sales summary per KNIT_SALE_NAME (สำหรับ morning greeting) ---
        sales_summary = _aggregate_sales(booking_rows)

        # --- ดึง KG_Ava_Display measure ผ่าน DAX query ---
        kg_ava_summary = ''
        try:
            result = _pbi_fetch_dax(_KG_AVA_DAX)
            kg_ava_rows = result.get('data', [])
            kg_ava_summary = _aggregate_kg_ava(kg_ava_rows)
            logger.info(f"DataCache: KG_Ava_Display loaded — {len(kg_ava_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to fetch KG_Ava_Display: {e}")
            fetch_failed = True

        with self._lock:
            if mc_summary or booking_summary:
                machine_payload = {
                    'success': True,
                    'data': {
                        'mc': mc_summary,
                        'booking': booking_summary,
                        'kg_ava': kg_ava_summary,
                    }
                }
                self._cache['query_machine'] = machine_payload
                self._cache['query_cap_ava'] = machine_payload
                self._ready['query_machine'] = bool(mc_summary)
                self._ready['query_cap_ava'] = bool(mc_summary)

            if booking_summary:
                self._cache['query_knit_plan'] = {'success': True, 'data': booking_summary}
                self._cache['query_booking'] = {'success': True, 'data': booking_summary}
                self._ready['query_knit_plan'] = True
                self._ready['query_booking'] = True

            if item_summary:
                self._cache['query_item'] = {'success': True, 'data': item_summary}
                self._ready['query_item'] = True

            if sales_summary:
                self._cache['query_sales'] = {'success': True, 'data': sales_summary}
                self._ready['query_sales'] = True

            self._last_refresh = datetime.now()
            self._row_counts = {
                'booking_master': len(booking_rows),
                'table_mc': len(mc_rows),
                'table_item': len(item_rows),
            }

        return not fetch_failed

    def get(self, key: str) -> Tuple[Optional[dict], bool]:
        with self._lock:
            return self._cache.get(key), self._ready.get(key, False)

    def is_ready(self, key: str) -> bool:
        with self._lock:
            return self._ready.get(key, False)

    def get_status(self) -> dict:
        with self._lock:
            return {
                'ready': {key: self._ready.get(key, False) for key in DATA_KEYS},
                'last_refresh': self._last_refresh.strftime('%Y-%m-%d %H:%M:%S') if self._last_refresh else None,
                'next_refresh': self._next_refresh.strftime('%Y-%m-%d %H:%M:%S') if self._next_refresh else None,
                'row_counts': dict(self._row_counts),
            }

    def get_sales_data(self, username: str) -> tuple[dict | None, bool]:
        """Find sales data for a username by matching against KNIT_SALE_NAME (case-insensitive).
        Returns (data, is_personal) where is_personal=False means system-wide fallback."""
        cached, ready = self.get('query_sales')
        if not ready or not cached:
            return None, False
        sales_map: dict = cached.get('data', {})
        username_lower = username.lower()
        # Exact match first
        if username_lower in sales_map:
            return sales_map[username_lower], True
        # Partial match: username contained in sales name or vice versa
        for key, data in sales_map.items():
            if key == '__system__':
                continue
            if username_lower in key or key in username_lower:
                return data, True
        # No match — return system-wide total
        system = sales_map.get('__system__')
        return system, False

    def force_refresh(self):
        """บังคับ refresh cache ทันที (เรียกจาก admin endpoint)"""
        import threading
        t = threading.Thread(target=self._refresh_all, daemon=True, name='ForceRefreshThread')
        t.start()
        t.join(timeout=120)


_instance: Optional[DataCache] = None


def get_data_cache() -> DataCache:
    global _instance
    if _instance is None:
        _instance = DataCache()
    return _instance
