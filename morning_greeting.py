import logging
import threading
import time
from datetime import datetime, timedelta, date
from datetime import time as dt_time

from data_cache import get_data_cache

logger = logging.getLogger(__name__)

_THAI_MONTHS = ['', 'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
                'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม']
_THAI_DAYS = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์', 'เสาร์', 'อาทิตย์']


def _current_yw() -> str:
    now = datetime.now()
    iso = now.isocalendar()
    return f"{iso[0]}{iso[1]:02d}"


def _parse_machine_summary(mc_csv: str, yw: str) -> dict | None:
    """Summarise Table_MC for the given week: total/used/available machines + groups with ava."""
    if not mc_csv:
        return None
    total = used = ava = 0.0
    groups_ava: list[str] = []
    seen_groups: set[str] = set()
    for line in mc_csv.splitlines()[1:]:  # header: YW,Group,Guage,Total,Used_N,Used_F,Ava
        cols = line.split(',')
        if len(cols) < 7 or cols[0].strip() != yw:
            continue
        try:
            total += float(cols[3].strip())
            used += float(cols[4].strip()) + float(cols[5].strip())
            row_ava = float(cols[6].strip())
            ava += row_ava
            group = cols[1].strip()
            if row_ava > 0 and group not in seen_groups:
                groups_ava.append(group)
                seen_groups.add(group)
        except (ValueError, IndexError):
            continue
    if total == 0:
        return None
    return {'total': round(total), 'used': round(used), 'ava': round(ava), 'groups_ava': groups_ava}


def _parse_kg_ava(kg_ava_csv: str, yw: str) -> list[dict]:
    """Parse KG_Ava CSV for the given week → [{group, kg_ava}]."""
    if not kg_ava_csv:
        return []
    result = []
    for line in kg_ava_csv.splitlines()[1:]:  # header: YW,Group,KG_Ava
        cols = line.split(',')
        if len(cols) < 3 or cols[0].strip() != yw:
            continue
        try:
            kg = float(cols[2].strip())
            if kg > 0:
                result.append({'group': cols[1].strip(), 'kg': kg})
        except (ValueError, IndexError):
            continue
    return result


def _parse_booking_summary(booking_csv: str, yw: str) -> list[dict]:
    """Parse booking CSV for the given week → [{group, used}]."""
    if not booking_csv:
        return []
    result = []
    for line in booking_csv.splitlines()[1:]:  # header: YW,MC_GROUP,Used
        cols = line.split(',')
        if len(cols) < 3 or cols[0].strip() != yw:
            continue
        try:
            result.append({'group': cols[1].strip(), 'used': float(cols[2].strip())})
        except (ValueError, IndexError):
            continue
    return result


def _analyze_issues(mc_csv: str, n_weeks: int = 3) -> list[str]:
    """Scan current + next n_weeks-1 weeks and return human-readable warning strings."""
    if not mc_csv:
        return []

    # Aggregate mc data per (yw, group): sum total & ava across all gauges
    mc: dict = {}
    for line in mc_csv.splitlines()[1:]:  # header: YW,Group,Guage,Total,Used_N,Used_F,Ava
        cols = line.split(',')
        if len(cols) < 7:
            continue
        try:
            yw, group = cols[0].strip(), cols[1].strip()
            total = float(cols[3].strip())
            ava   = float(cols[6].strip())
            key = (yw, group)
            if key not in mc:
                mc[key] = {'total': 0.0, 'ava': 0.0}
            mc[key]['total'] += total
            mc[key]['ava']   += ava
        except (ValueError, IndexError):
            continue

    now = datetime.now()
    current_yw = _current_yw()
    weeks = []
    for i in range(n_weeks):
        d = now + timedelta(weeks=i)
        iso = d.isocalendar()
        weeks.append(f"{iso[0]}{iso[1]:02d}")

    # Collect raw issues with sort key: (week_index, usage_pct desc)
    raw: list[tuple[int, float, str]] = []  # (week_idx, usage_pct, text)
    for yw in weeks:
        week_num = str(int(yw[-2:]))
        week_idx = weeks.index(yw)
        label = f"WK {week_num}" + (" (สัปดาห์นี้)" if yw == current_yw else f" (+{week_idx} สัปดาห์)")
        for (w, group), data in sorted(mc.items()):
            if w != yw:
                continue
            total, ava = data['total'], data['ava']
            if total <= 0:
                continue
            usage_pct = (total - ava) / total * 100
            if ava <= 0:
                raw.append((week_idx, 100.0,
                    f"• กลุ่ม **{group}** {label}: เครื่อง**เต็มแล้ว** (จองครบ {total:.0f} เครื่อง)"))
            elif usage_pct >= 85:
                raw.append((week_idx, usage_pct,
                    f"• กลุ่ม **{group}** {label}: เครื่อง**ใกล้เต็ม** (ว่างเหลือ {ava:.0f}/{total:.0f} เครื่อง — {100-usage_pct:.0f}%)"))

    # Sort: สัปดาห์ใกล้ก่อน, usage สูงก่อน → เอา 5 อันดับแรก
    raw.sort(key=lambda x: (x[0], -x[1]))
    return [text for _, _, text in raw[:5]]


def _parse_item_summary(item_csv: str, yw: str) -> tuple[int, float]:
    """Count unique items and sum KP_Weight for the given week from query_item CSV.
    Header: Item,Group,KP_Weight,YW"""
    if not item_csv:
        return 0, 0.0
    items: set[str] = set()
    total_kg = 0.0
    for line in item_csv.splitlines()[1:]:
        cols = line.split(',')
        if len(cols) < 4 or cols[3].strip() != yw:
            continue
        try:
            items.add(cols[0].strip())
            kp = cols[2].strip()
            total_kg += float(kp) if kp else 0.0
        except (ValueError, IndexError):
            continue
    return len(items), total_kg


def build_greeting_text(
    username: str,
    mc_csv: str | None,
    kg_ava_csv: str | None,
    booking_csv: str | None,
    item_summary_csv: str | None,
) -> str:
    now = datetime.now()
    day_name = _THAI_DAYS[now.weekday()]
    date_str = f"วัน{day_name}ที่ {now.day} {_THAI_MONTHS[now.month]} {now.year + 543}"
    current_yw = _current_yw()
    week_num = str(int(current_yw[-2:]))

    lines = [f"สวัสดีตอนเช้าค่ะ คุณ {username} ☀️", date_str, ""]

    # --- ITEM (system-wide from query_item) ---
    item_count, total_kg = _parse_item_summary(item_summary_csv or '', current_yw)
    if item_count > 0:
        lines += [
            "📋 **ภาพรวมแผนการผลิต**",
            f"• มี **{item_count} Items** / **{total_kg:,.0f} kg** อยู่ในแผนการผลิต",
            "",
        ]
    else:
        lines += ["📋 ข้อมูลแผนการผลิตยังไม่พร้อม", ""]

    # --- MACHINE ---
    mc = _parse_machine_summary(mc_csv or '', current_yw)
    if mc:
        lines += [
            f"⚙️ **Machine สัปดาห์นี้ (WK {week_num})**",
            f"• ทั้งหมด **{mc['total']} เครื่อง** | ใช้งาน **{mc['used']}** | ว่าง **{mc['ava']} เครื่อง**",
        ]
        if mc['groups_ava']:
            lines.append(f"• กลุ่มที่มีเครื่องว่าง: {', '.join(mc['groups_ava'])}")
        lines.append("")

    # --- AVAILABLE (KG) ---
    kg_rows = _parse_kg_ava(kg_ava_csv or '', current_yw)
    if kg_rows:
        total_kg = sum(r['kg'] for r in kg_rows)
        lines.append(f"📦 **Available Capacity สัปดาห์นี้ (WK {week_num})**")
        for r in kg_rows[:5]:
            lines.append(f"• {r['group']} = **{r['kg']:,.0f} kg**")
        if len(kg_rows) > 5:
            lines.append(f"• ... และอีก {len(kg_rows) - 5} กลุ่ม")
        lines.append(f"• รวม **{total_kg:,.0f} kg**")
        lines.append("")

    # --- KNITTING PLAN ---
    booking_rows = _parse_booking_summary(booking_csv or '', current_yw)
    if booking_rows:
        total_used = sum(r['used'] for r in booking_rows)
        lines.append(f"🧵 **Knitting Plan สัปดาห์นี้ (WK {week_num})**")
        for r in booking_rows[:5]:
            lines.append(f"• {r['group']} จอง **{r['used']:.0f} เครื่อง**")
        if len(booking_rows) > 5:
            lines.append(f"• ... และอีก {len(booking_rows) - 5} กลุ่ม")
        lines.append(f"• รวมจอง **{total_used:.0f} เครื่อง**")
        lines.append("")

    # --- ISSUES ---
    issues = _analyze_issues(mc_csv or '')
    if issues:
        lines.append("⚠️ **ประเด็นที่ควรระวัง (3 สัปดาห์ข้างหน้า)**")
        lines += issues
        lines.append("")

    lines.append("น้อง I-SAVE Chatbot ยินดีให้บริการค่ะ สามารถสอบถามข้อมูลได้เลยนะคะ 😊")
    return "\n".join(lines)


class MorningGreetingScheduler:
    def __init__(self, db):
        self._db = db
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name='MorningGreetingThread')
        self._thread.start()
        logger.info("MorningGreetingScheduler: started — targeting 08:00 daily")

    def _next_8am(self) -> datetime:
        now = datetime.now()
        today_8am = datetime.combine(now.date(), dt_time(8, 0))
        if now < today_8am:
            return today_8am
        return datetime.combine(now.date() + timedelta(days=1), dt_time(8, 0))

    def _run(self):
        # On startup: catch up if server started after 8 AM and greetings weren't sent yet
        self._send_all_greetings()

        while True:
            next_time = self._next_8am()
            sleep_secs = max((next_time - datetime.now()).total_seconds(), 0)
            logger.info(f"MorningGreetingScheduler: next run at {next_time.strftime('%Y-%m-%d %H:%M')} (in {sleep_secs/3600:.1f}h)")
            time.sleep(sleep_secs)
            logger.info("MorningGreetingScheduler: 08:00 reached — sending morning greetings")
            self._send_all_greetings()

    def _send_all_greetings(self):
        now = datetime.now()
        if now.hour < 8:
            return  # Don't send before 8 AM

        try:
            users = [u for u in self._db.get_all_users() if u.get('is_active') and u.get('role') != 'admin']
            mc_cached, mc_ready = get_data_cache().get('query_machine')
            mc_data = mc_cached.get('data', {}) if mc_ready and mc_cached else {}
            mc_csv     = mc_data.get('mc', '')
            kg_ava_csv = mc_data.get('kg_ava', '')
            booking_cached, _ = get_data_cache().get('query_booking')
            booking_csv = booking_cached.get('data', '') if booking_cached else ''
            item_cached, _ = get_data_cache().get('query_item')
            item_csv = item_cached.get('data', '') if item_cached else ''

            count = 0
            for user in users:
                try:
                    if self._db.has_morning_greeting_today(user['id']):
                        continue
                    text = build_greeting_text(user['username'], mc_csv, kg_ava_csv, booking_csv, item_csv)
                    today = date.today()
                    conv_id = self._db.create_conversation(user['id'], f"I-SAVE News {today.day:02d}/{today.month:02d}")
                    self._db.add_message(conv_id, 'assistant', text, 'text')
                    self._db.record_morning_greeting(user['id'], conv_id)
                    count += 1
                    logger.info(f"MorningGreetingScheduler: sent greeting to '{user['username']}'")
                except Exception as e:
                    logger.error(f"MorningGreetingScheduler: failed for user '{user.get('username')}': {e}")

            logger.info(f"MorningGreetingScheduler: done — {count} greetings sent")
        except Exception as e:
            logger.error(f"MorningGreetingScheduler: _send_all_greetings error: {e}")

    def send_now(self) -> dict:
        """Force-send greetings immediately regardless of time (for admin testing).
        Runs synchronously and returns {sent, skipped, errors, usernames}."""
        result = {'sent': 0, 'skipped': 0, 'errors': 0, 'usernames': []}
        try:
            all_users = self._db.get_all_users()
            users = [u for u in all_users if u.get('is_active') and u.get('role') != 'admin']
            mc_cached, mc_ready = get_data_cache().get('query_machine')
            mc_data = mc_cached.get('data', {}) if mc_ready and mc_cached else {}
            mc_csv     = mc_data.get('mc', '')
            kg_ava_csv = mc_data.get('kg_ava', '')
            booking_cached, _ = get_data_cache().get('query_booking')
            booking_csv = booking_cached.get('data', '') if booking_cached else ''
            item_cached, _ = get_data_cache().get('query_item')
            item_csv = item_cached.get('data', '') if item_cached else ''

            today = date.today()
            for user in users:
                try:
                    text = build_greeting_text(user['username'], mc_csv, kg_ava_csv, booking_csv, item_csv)
                    conv_id = self._db.create_conversation(user['id'], f"I-SAVE News {today.day:02d}/{today.month:02d}")
                    self._db.add_message(conv_id, 'assistant', text, 'text')
                    self._db.record_morning_greeting(user['id'], conv_id)
                    result['sent'] += 1
                    result['usernames'].append(user['username'])
                    logger.info(f"MorningGreetingScheduler.send_now: sent to '{user['username']}'")
                except Exception as e:
                    result['errors'] += 1
                    logger.error(f"MorningGreetingScheduler.send_now: failed for '{user.get('username')}': {e}")

            logger.info(f"MorningGreetingScheduler.send_now: {result['sent']} sent, {result['errors']} errors")
        except Exception as e:
            logger.error(f"MorningGreetingScheduler.send_now error: {e}")
            result['errors'] += 1
        return result
