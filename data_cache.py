import logging
import os
import threading
import time
from datetime import datetime, timedelta
from datetime import time as dt_time
from typing import Dict, Optional, Tuple

from collections import defaultdict

from dotenv import load_dotenv
from powerbi_connector import fetch_table as _pbi_fetch_table

load_dotenv()

logger = logging.getLogger(__name__)

REFRESH_HOURS = (5, 12, 20)  # 05:00, 12:00, 20:00

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
        group = str(r.get('Master.Group', '') or '').strip()
        kp_raw = r.get('KP_Weight')
        yw = str(r.get('YW', '') or '').strip()
        if not item or not yw or not (min_yw <= yw <= max_yw):
            continue
        kp = str(kp_raw) if kp_raw is not None else ''
        lines.append(f"{item},{group},{kp},{yw}")
    return '\n'.join(lines)


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
        self._refresh_all()

        while True:
            next_time = self._next_refresh_time()
            with self._lock:
                self._next_refresh = next_time
            sleep_secs = max((next_time - datetime.now()).total_seconds(), 0)
            logger.info(f"DataCache: next refresh at {next_time.strftime('%H:%M')} (in {sleep_secs/3600:.1f}h)")
            time.sleep(sleep_secs)
            logger.info("DataCache: scheduled refresh starting...")
            self._refresh_all()

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

    def _refresh_all(self):
        # --- ดึง BookingMaster ---
        booking_rows = []
        try:
            result = _pbi_fetch_table(_TABLE_BOOKING)
            booking_rows = result.get('data', [])
            logger.info(f"DataCache: BookingMaster loaded — {len(booking_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to load BookingMaster: {e}")

        # --- ดึง Table_MC ---
        mc_rows = []
        try:
            result = _pbi_fetch_table(_TABLE_MC)
            mc_rows = result.get('data', [])
            logger.info(f"DataCache: Table_MC loaded — {len(mc_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to load Table_MC: {e}")

        # --- ดึง Table_Item ---
        item_rows = []
        try:
            result = _pbi_fetch_table(_TABLE_ITEM)
            item_rows = result.get('data', [])
            logger.info(f"DataCache: Table_Item loaded — {len(item_rows)} rows")
        except Exception as e:
            logger.error(f"DataCache: failed to load Table_Item: {e}")

        # --- Aggregate Table_MC: group by YW + Master.MC ---
        mc_summary = _aggregate_mc(mc_rows)

        # --- Aggregate BookingMaster: group by YW + MC_GROUP ---
        booking_summary = _aggregate_booking(booking_rows)

        # --- Item plan จาก BookingMaster โดยตรง (ITEM_CODE + YW + KP_Weight) ---
        item_summary = _aggregate_item_plan(booking_rows)

        with self._lock:
            if mc_summary or booking_summary:
                machine_payload = {
                    'success': True,
                    'data': {
                        'mc': mc_summary,
                        'booking': booking_summary,
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

            self._last_refresh = datetime.now()
            self._row_counts = {
                'booking_master': len(booking_rows),
                'table_mc': len(mc_rows),
                'table_item': len(item_rows),
            }

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
