"""เทส rate limiter — กัน spam หน้าแชต และไม่ทำของเดิม (login/forgot) พัง."""
import pytest

import rate_limit
from rate_limit import is_rate_limited, RATE_MAX_CHAT, RATE_MAX_FORGOT, RATE_MAX_LOGIN, _RATE_WINDOW_BY_BUCKET


@pytest.fixture(autouse=True)
def _clean_state():
    """ล้าง state ก่อนทุกเทส เพื่อไม่ให้ count ค้างข้ามเคส."""
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_chat_allows_up_to_limit_then_blocks():
    # ส่งได้ครบ RATE_MAX_CHAT ข้อความแรก
    for i in range(RATE_MAX_CHAT):
        assert is_rate_limited("user-1", "chat") is False, f"ข้อความที่ {i+1} ไม่ควรถูกบล็อก"
    # ข้อความถัดไปต้องถูกบล็อก
    assert is_rate_limited("user-1", "chat") is True


def test_chat_is_per_user_not_shared():
    # user-1 ยิงจนเต็ม
    for _ in range(RATE_MAX_CHAT + 5):
        is_rate_limited("user-1", "chat")
    # user-2 (เช่น IP/NAT เดียวกันแต่คนละ user) ต้องไม่โดนผลกระทบ
    assert is_rate_limited("user-2", "chat") is False


def test_buckets_are_independent():
    # chat เต็มแล้วต้องไม่ไปกระทบโควต้า login ของ identifier เดียวกัน
    for _ in range(RATE_MAX_CHAT + 1):
        is_rate_limited("same-id", "chat")
    assert is_rate_limited("same-id", "login") is False


def test_login_default_limit_unchanged():
    for _ in range(RATE_MAX_LOGIN):
        assert is_rate_limited("ip-a", "login") is False
    assert is_rate_limited("ip-a", "login") is True


def test_forgot_limit_unchanged():
    for _ in range(RATE_MAX_FORGOT):
        assert is_rate_limited("ip-b", "forgot") is False
    assert is_rate_limited("ip-b", "forgot") is True


def test_window_expiry_resets_count(monkeypatch):
    """เมื่อพ้น window แล้ว ความพยายามเก่าต้องถูกลืม ส่งได้อีก."""
    fake = {"t": 1000.0}
    monkeypatch.setattr(rate_limit.time, "time", lambda: fake["t"])

    for _ in range(RATE_MAX_CHAT):
        is_rate_limited("user-x", "chat")
    assert is_rate_limited("user-x", "chat") is True  # เต็มแล้ว

    # ขยับเวลาเลย window ไป (chat window + 1 วินาที)
    fake["t"] += _RATE_WINDOW_BY_BUCKET['chat'] + 1
    assert is_rate_limited("user-x", "chat") is False  # นับใหม่ได้
