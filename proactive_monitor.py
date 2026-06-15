import logging
import threading
import time
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from data_cache import get_data_cache

logger = logging.getLogger(__name__)

_BKK = ZoneInfo("Asia/Bangkok")

_CHECK_INTERVAL_SECS = 3600  # ตรวจทุก 1 ชั่วโมง
_STARTUP_DELAY_SECS = 90     # รอให้ DataCache โหลดก่อน

# ส่งแจ้งเตือนได้เฉพาะช่วง 06:00–22:00
_SEND_HOUR_START = 6
_SEND_HOUR_END = 22

# threshold เดิมจาก morning_greeting._analyze_issues
_NEAR_FULL_PCT = 85


def _current_yw() -> str:
    now = datetime.now(_BKK)
    iso = now.isocalendar()
    return f"{iso[0]}{iso[1]:02d}"


def _detect_capacity_alerts(mc_csv: str, n_weeks: int = 3) -> list[dict]:
    """สแกน mc_csv และคืน list ของ alert dict พร้อม key สำหรับ dedup"""
    if not mc_csv:
        return []

    # รวม total & ava ของทุก gauge ต่อ (yw, group)
    mc: dict = {}
    for line in mc_csv.splitlines()[1:]:
        cols = line.split(',')
        if len(cols) < 7:
            continue
        try:
            yw, group = cols[0].strip(), cols[1].strip()
            total = float(cols[3].strip())
            ava = float(cols[6].strip())
            key = (yw, group)
            if key not in mc:
                mc[key] = {'total': 0.0, 'ava': 0.0}
            mc[key]['total'] += total
            mc[key]['ava'] += ava
        except (ValueError, IndexError):
            continue

    now = datetime.now(_BKK)
    current_yw = _current_yw()
    weeks = []
    for i in range(n_weeks):
        d = now + timedelta(weeks=i)
        iso = d.isocalendar()
        weeks.append(f"{iso[0]}{iso[1]:02d}")

    alerts = []
    for yw in weeks:
        week_idx = weeks.index(yw)
        week_num = str(int(yw[-2:]))
        label = f"WK {week_num}" + (" (สัปดาห์นี้)" if yw == current_yw else f" (+{week_idx} สัปดาห์)")
        for (w, group), data in sorted(mc.items()):
            if w != yw:
                continue
            total, ava = data['total'], data['ava']
            if total <= 0:
                continue
            usage_pct = (total - ava) / total * 100
            if ava <= 0:
                alerts.append({
                    'key': f"{yw}_{group}_full",
                    'yw': yw,
                    'group': group,
                    'severity': 'full',
                    'label': label,
                    'message': f"กลุ่ม **{group}** {label}: เครื่อง**เต็มแล้ว** (จองครบ {total:.0f} เครื่อง)",
                    'week_idx': week_idx,
                    'usage_pct': 100.0,
                })
            elif usage_pct >= _NEAR_FULL_PCT:
                alerts.append({
                    'key': f"{yw}_{group}_near_full",
                    'yw': yw,
                    'group': group,
                    'severity': 'near_full',
                    'label': label,
                    'message': f"กลุ่ม **{group}** {label}: เครื่อง**ใกล้เต็ม** (ว่างเหลือ {ava:.0f}/{total:.0f} เครื่อง — {100 - usage_pct:.0f}%)",
                    'week_idx': week_idx,
                    'usage_pct': usage_pct,
                })

    alerts.sort(key=lambda x: (x['week_idx'], -x['usage_pct']))
    return alerts


def _build_alert_message(alerts: list[dict]) -> str:
    now = datetime.now(_BKK)
    time_str = now.strftime('%H:%M น.')
    lines = [
        "🚨 **แจ้งเตือนอัตโนมัติ**",
        f"น้อง I-SAVE ตรวจพบสถานการณ์ที่ควรระวัง *(ข้อมูล ณ {time_str})*",
        "",
    ]
    full_alerts = [a for a in alerts if a['severity'] == 'full']
    near_alerts = [a for a in alerts if a['severity'] == 'near_full']
    if full_alerts:
        lines.append("🔴 **เต็มแล้ว**")
        for a in full_alerts:
            lines.append(f"• {a['message']}")
        lines.append("")
    if near_alerts:
        lines.append(f"⚠️ **ใกล้เต็ม (≥{_NEAR_FULL_PCT}%)**")
        for a in near_alerts:
            lines.append(f"• {a['message']}")
        lines.append("")
    lines.append("สามารถถามน้องได้เลยว่าต้องการดูรายละเอียดกลุ่มไหนค่ะ 😊")
    return "\n".join(lines)


class ProactiveMonitor:
    def __init__(self, db):
        self._db = db
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name='ProactiveMonitorThread')
        self._thread.start()
        logger.info("ProactiveMonitor: started — checking every hour (06:00–22:00)")

    def _can_send_now(self) -> bool:
        hour = datetime.now(_BKK).hour
        return _SEND_HOUR_START <= hour < _SEND_HOUR_END

    def _run(self):
        time.sleep(_STARTUP_DELAY_SECS)
        while True:
            self._check_and_alert()
            time.sleep(_CHECK_INTERVAL_SECS)

    def _check_and_alert(self):
        if not self._can_send_now():
            return
        try:
            mc_cached, mc_ready = get_data_cache().get('query_machine')
            if not mc_ready or not mc_cached:
                return
            mc_csv = mc_cached.get('data', {}).get('mc', '')
            if not mc_csv:
                return

            all_alerts = _detect_capacity_alerts(mc_csv, n_weeks=3)
            new_alerts = [a for a in all_alerts if not self._db.has_alert_sent_today(a['key'])]
            if not new_alerts:
                return

            logger.info(f"ProactiveMonitor: {len(new_alerts)} new alert(s) — notifying users")
            users = [u for u in self._db.get_all_users() if u.get('is_active') and u.get('role') != 'admin']
            msg = _build_alert_message(new_alerts)
            today = date.today()

            sent = 0
            for user in users:
                try:
                    conv_id = self._db.create_conversation(
                        user['id'],
                        f"🌤️ สรุปประจำวัน {today.day:02d}/{today.month:02d}"
                    )
                    self._db.add_message(conv_id, 'assistant', msg, 'text')
                    sent += 1
                except Exception as e:
                    logger.error(f"ProactiveMonitor: failed to notify '{user.get('username')}': {e}")

            for a in new_alerts:
                try:
                    self._db.record_alert(a['key'])
                except Exception as e:
                    logger.warning(f"ProactiveMonitor: failed to record alert '{a['key']}': {e}")

            logger.info(f"ProactiveMonitor: done — {sent}/{len(users)} users notified")
        except Exception as e:
            logger.error(f"ProactiveMonitor: _check_and_alert error: {e}")

    def check_now(self) -> dict:
        """Force-check ทันที (สำหรับ admin testing). คืน summary dict."""
        result = {'new_alerts': 0, 'total_alerts': 0, 'users_notified': 0, 'errors': 0, 'alerts': []}
        try:
            mc_cached, mc_ready = get_data_cache().get('query_machine')
            if not mc_ready or not mc_cached:
                result['error'] = 'cache not ready'
                return result
            mc_csv = mc_cached.get('data', {}).get('mc', '')
            all_alerts = _detect_capacity_alerts(mc_csv, n_weeks=3)
            result['total_alerts'] = len(all_alerts)
            new_alerts = [a for a in all_alerts if not self._db.has_alert_sent_today(a['key'])]
            result['new_alerts'] = len(new_alerts)
            result['alerts'] = [{'key': a['key'], 'message': a['message']} for a in new_alerts]

            if not new_alerts:
                return result

            users = [u for u in self._db.get_all_users() if u.get('is_active') and u.get('role') != 'admin']
            msg = _build_alert_message(new_alerts)
            today = date.today()

            for user in users:
                try:
                    conv_id = self._db.create_conversation(
                        user['id'],
                        f"🌤️ สรุปประจำวัน {today.day:02d}/{today.month:02d}"
                    )
                    self._db.add_message(conv_id, 'assistant', msg, 'text')
                    result['users_notified'] += 1
                except Exception as e:
                    result['errors'] += 1
                    logger.error(f"ProactiveMonitor.check_now: failed for '{user.get('username')}': {e}")

            for a in new_alerts:
                try:
                    self._db.record_alert(a['key'])
                except Exception as e:
                    logger.warning(f"ProactiveMonitor.check_now: failed to record '{a['key']}': {e}")

        except Exception as e:
            result['errors'] += 1
            logger.error(f"ProactiveMonitor.check_now error: {e}")
        return result


_instance: ProactiveMonitor | None = None


def get_proactive_monitor(db=None) -> ProactiveMonitor:
    global _instance
    if _instance is None:
        if db is None:
            raise ValueError("db required on first call")
        _instance = ProactiveMonitor(db)
    return _instance
