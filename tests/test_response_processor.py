"""เทส response_processor — helper ล้วนๆ + พฤติกรรม retry/ซ่อน error ของ process_message."""
import asyncio
import types
from datetime import datetime, timedelta

import pytest

import response_processor as rp
from response_processor import (
    _clean_response,
    _detect_reply_language,
    _yw_from_date,
    _min_plannable_yw,
    _week_keyword_to_yw,
)


# ---------- pure helpers ----------
def test_clean_response_collapses_blank_lines():
    assert _clean_response("a\n\n\n\nb") == "a\n\nb"


def test_clean_response_removes_gap_between_bullets():
    assert _clean_response("- one\n\n- two") == "- one\n- two"


def test_detect_language_thai_from_message():
    assert _detect_reply_language("สวัสดีครับ") == "thai"


def test_detect_language_english_from_message():
    assert _detect_reply_language("show me the plan") == "english"


def test_detect_language_falls_back_to_thai_history_for_bare_item_code():
    # ข้อความเป็น item code ล้วน (ไม่มีสัญญาณภาษา) -> ดู history
    history = [{"role": "user", "content": "ขอแผนทอหน่อย"}]
    assert _detect_reply_language("F100114/10A0", history) == "thai"


def test_min_plannable_yw_is_two_weeks_ahead():
    assert _min_plannable_yw() == _yw_from_date(datetime.now() + timedelta(weeks=2))


def test_week_keyword_explicit_week_number():
    year = datetime.now().year
    assert f"{year}22" in _week_keyword_to_yw("ขอข้อมูล week 22")


def test_week_keyword_explicit_six_digit_yw():
    assert "202627" in _week_keyword_to_yw("ดู 202627 ให้หน่อย")


def test_week_keyword_relative_next_week():
    expected = _yw_from_date(datetime.now() + timedelta(weeks=1))
    assert expected in _week_keyword_to_yw("สัปดาห์หน้า")


def test_week_keyword_empty_when_no_date():
    assert _week_keyword_to_yw("สวัสดีครับ") == []


# ---------- process_message: retry / error hiding ----------
def _make_proc():
    return rp.ResponseProcessor()


def _fake_client(create_fn):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create_fn))
    )


def test_process_message_retries_then_hides_raw_error(monkeypatch):
    monkeypatch.setattr(rp, "OPENAI_RETRY_BACKOFF", 0)  # เร่งเทส
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("SECRET-INTERNAL-xyz")

    proc = _make_proc()
    proc._openai = _fake_client(boom)

    res = asyncio.run(proc.process_message("สวัสดี"))

    assert calls["n"] == rp.OPENAI_MAX_RETRIES + 1          # ลองครบ (1 + retries)
    assert "SECRET-INTERNAL" not in res.message            # error ดิบต้องไม่หลุด
    assert res.metadata["intent"] == "error"


def test_process_message_recovers_after_one_failure(monkeypatch):
    monkeypatch.setattr(rp, "OPENAI_RETRY_BACKOFF", 0)
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient blip")
        msg = types.SimpleNamespace(content="ตอบสำเร็จค่ะ", tool_calls=None)
        choice = types.SimpleNamespace(finish_reason="stop", message=msg)
        return types.SimpleNamespace(choices=[choice], usage=None)

    proc = _make_proc()
    proc._openai = _fake_client(flaky)

    res = asyncio.run(proc.process_message("สวัสดี"))

    assert calls["n"] == 2
    assert "ตอบสำเร็จ" in res.message
    assert res.metadata["intent"] != "error"


def test_process_message_shortcut_does_not_call_openai():
    """ปุ่มลัด (เช่น 'ข้อมูล Item') ต้องตอบจาก builder ไม่แตะ OpenAI เลย."""
    proc = _make_proc()

    def must_not_call(*a, **k):
        raise AssertionError("shortcut ไม่ควรเรียก OpenAI")

    proc._openai = _fake_client(must_not_call)
    res = asyncio.run(proc.process_message("ข้อมูล Item"))
    assert res.processing_path == "shortcut"
