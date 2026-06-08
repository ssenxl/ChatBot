"""Rate limiter แบบ in-memory (sliding window) ต่อ identifier ต่อ bucket.

แยกออกมาจาก chatbot_app เพื่อให้ unit-test ได้โดยไม่ต้องโหลดทั้ง Flask app/DB.
ใช้กัน brute-force หน้า login/forgot และกัน spam/abuse หน้าแชต.
"""
import threading
import time
from collections import defaultdict

_rate_lock = threading.Lock()
_rate_attempts: dict = defaultdict(list)

RATE_WINDOW = 300       # ช่วงเวลา default (วินาที) = 5 นาที (ใช้กับ login)
RATE_MAX_LOGIN = 10     # ครั้ง/identifier/window สำหรับ login (ค่า default)
RATE_MAX_FORGOT = 5     # ครั้ง/identifier/window สำหรับ forgot password
RATE_MAX_CHAT = 5       # ข้อความ/user/window สำหรับหน้าแชต

_RATE_MAX_BY_BUCKET = {
    'forgot': RATE_MAX_FORGOT,
    'chat': RATE_MAX_CHAT,
}

_RATE_WINDOW_BY_BUCKET = {
    'forgot': 300,
    'chat': 60,   # 1 นาที
}


def is_rate_limited(identifier: str, bucket: str = 'login') -> bool:
    """คืน True ถ้า identifier (เช่น IP หรือ user_id) ใน bucket นี้ส่งเกินโควต้าในช่วง window.
    ถ้ายังไม่เกิน จะบันทึกครั้งนี้แล้วคืน False."""
    max_attempts = _RATE_MAX_BY_BUCKET.get(bucket, RATE_MAX_LOGIN)
    window = _RATE_WINDOW_BY_BUCKET.get(bucket, RATE_WINDOW)
    now = time.time()
    key = f"{bucket}:{identifier}"
    with _rate_lock:
        _rate_attempts[key] = [t for t in _rate_attempts[key] if now - t < window]
        if len(_rate_attempts[key]) >= max_attempts:
            return True
        _rate_attempts[key].append(now)
        return False


def reset() -> None:
    """ล้าง state ทั้งหมด — ใช้ใน test เพื่อแยก case ออกจากกัน."""
    with _rate_lock:
        _rate_attempts.clear()
