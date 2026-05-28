import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging
from openai import OpenAI
from data_cache import get_data_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


@dataclass
class ProcessedResponse:
    message: str
    response_type: str  # 'text', 'data', 'chart', 'table'
    data: Optional[Dict] = None
    metadata: Optional[Dict] = None
    suggestions: Optional[List[str]] = None
    processing_path: str = 'agent'
    mcp_calls: Optional[List[Dict]] = None


def _clean_response(text: str) -> str:
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove blank line between consecutive bullets
    _bullet_gap = re.compile(r'([ \t]*[-•*][^\n]+)\n\n([ \t]*[-•*])', re.MULTILINE)
    while _bullet_gap.search(text):
        text = _bullet_gap.sub(r'\1\n\2', text)
    # Remove blank line between non-bullet text and a bullet
    text = re.sub(r'([^\n]+)\n\n([ \t]*[-•*])', r'\1\n\2', text)
    # Remove blank line between a bullet and following non-bullet text
    text = re.sub(r'([ \t]*[-•*][^\n]+)\n\n([^-•*\n])', r'\1\n\2', text)
    return text.strip()


def _has_thai(text: str) -> bool:
    return bool(re.search(r'[฀-๿]', text))


def _has_english_words(text: str) -> bool:
    # Strip item-code-style tokens (must contain a digit or slash, e.g. F100114/10A0, SKP28G)
    # Pure uppercase words like "OK", "YES" are NOT stripped so they're detected as English.
    stripped = re.sub(r'\b[A-Z][A-Z0-9/\-]*(?=[0-9/])[A-Z0-9/\-]*\b', '', text)
    return bool(re.search(r'\b[a-zA-Z]{2,}\b', stripped))


def _detect_reply_language(message: str, history: Optional[List[Dict]] = None) -> str:
    """Return 'thai' or 'english'.
    - Any Thai character in message → Thai
    - No Thai + has English words → English
    - No signal → check recent history, default Thai
    """
    if _has_thai(message):
        return 'thai'
    if _has_english_words(message):
        return 'english'

    # No signal (e.g. bare item code) — fall back to recent history
    if history:
        for msg in reversed(history[-6:]):
            content = msg.get('content') or msg.get('message', '')
            if _has_thai(content):
                return 'thai'
            if _has_english_words(content):
                return 'english'

    return 'thai'


def _min_plannable_yw() -> str:
    future = datetime.now() + timedelta(weeks=2)
    iso = future.isocalendar()
    return f"{iso[0]}{iso[1]:02d}"


def _week_keyword_to_yw(text: str) -> list:
    year = datetime.now().year
    yw_list = []
    patterns = [
        r'\bweek\s*(\d{1,2})\b',
        r'\bwk(\d{1,2})\b',
        r'\bw(\d{2})\b',              # "w22" (2-digit only) — avoids "w5", "w8" false positives
        r'สัปดาห์(?:ที่)?\s*(\d{1,2})',
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text.lower()):
            week_num = int(m.group(1))
            if 1 <= week_num <= 53:
                yw = f"{year}{week_num:02d}"
                if yw not in yw_list:
                    yw_list.append(yw)
    return yw_list


def _group_matches(group_col: str, keywords: list) -> bool:
    for kw in keywords:
        if group_col == kw:
            return True
        if group_col.startswith(kw):
            rest = group_col[len(kw):]
            if rest and not rest[0].isalpha():
                return True
    return False


SYSTEM_PROMPT_TEMPLATE = """You are an AI assistant for the I-SAVE system at a textile factory.
คุณเป็นผู้ช่วย AI ของระบบ I-SAVE สำหรับโรงงานทอผ้า ชื่อว่า "น้อง I-SAVE Chatbot"

LANGUAGE RULE (highest priority — overrides ALL template responses below):
- Item codes (e.g. F100114/10A0), machine group names (e.g. SKP 28G), and technical codes are NOT language indicators — ignore them when detecting language.
- If the user's non-code text is Thai (or no non-code text exists) → reply in Thai
- If the user's non-code text is clearly English → reply in English
- If mixed → follow the dominant non-code language; default to Thai when unclear
- Always translate any template response to match the detected language.

คุณมี tools สำหรับดึงข้อมูลจากระบบ ให้เรียก tool ก่อนตอบทุกครั้งที่คำถามเกี่ยวกับข้อมูล:
- get_item_plan        : แผน item (กลุ่มเครื่อง, KP_Weight, สัปดาห์ที่วางแผน)
- get_machine_capacity : กำลังการผลิต (Total, Used_N, Used_F, Ava=available machines)
- get_booking          : การจองเครื่องต่อกลุ่มต่อสัปดาห์
- get_knit_plan        : แผนการทอ (item, กลุ่ม, KP_Weight ตามสัปดาห์)

กฎสำคัญ:
1. ตรวจ conversation history ก่อนตอบ — ห้ามตอบซ้ำเฉพาะเมื่อ **ทั้ง item/กลุ่ม/สัปดาห์ AND ประเด็นคำถาม** เหมือนกันทุกอย่าง:
   - ห้ามซ้ำ: ถามซ้ำทุกอย่างเหมือนเดิม เช่น "item X week 22 มีกี่ตัน" แล้วถาม "item X week 22 มีกี่ตัน" อีกรอบ
   - ต้องตอบใหม่: item เดิมแต่ **สัปดาห์ต่างกัน**, item เดิมแต่ **ถามคนละหน่วย (kg vs ตัน)**, item เดิมแต่ **ถามคนละประเด็น (กลุ่มเครื่อง vs KP Weight vs capacity)**
   - ต้องตอบใหม่: คำถามที่เพิ่มเงื่อนไข เช่น "สัปดาห์ที่ 28 มีไหม" หลังจากเคยถามภาพรวมแล้ว
   - ห้าม re-fetch ข้อมูลชุดเดิมที่ตอบไปแล้วทุกประเด็นครบถ้วนแล้ว
   - ถ้า message ใหม่ไม่ได้ถามเรื่องข้อมูล ห้ามเรียก tool เด็ดขาด
2. ถ้าคำถามเกี่ยวกับข้อมูลในระบบ ให้เรียก tool ก่อนเสมอ อย่าตอบจากความรู้ตัวเอง
3. ต้องการข้อมูลหลายอย่าง → เรียก tool ได้หลายครั้ง
4. YW = week code in format YYYYWW e.g. 202622 = year 2026 week 22
5. Earliest plannable week = YW {min_yw} (current +2 weeks) — exclude YW below this
6. Ava = available machines (Total − Used_N − Used_F)
7. Be concise. Use bold (**text**) for key numbers. Use exactly ONE newline (\\n) between each bullet and between paragraphs. NEVER put multiple bullets on the same line. No blank lines (double newlines \\n\\n) anywhere in the response.
   - If tool result contains a line starting with [หมายเหตุ:...], you MUST include that warning in your response.
   - If tool result contains TOTAL_KP_WEIGHT=..., use that exact value for the total — never compute the sum yourself. Do NOT copy or show the [TOTAL_KP_WEIGHT=...] line in your response; it is for your internal use only.
8. When user greets (สวัสดี, hello, hi, etc.) — greeting คือคำทักทายล้วนๆ เท่านั้น:
   - Thai: "สวัสดีค่ะ น้อง I-SAVE Chatbot ค่ะพี่ๆ สามารถสอบถามข้อมูล หรือพิมพ์คำถามที่ต้องการได้เลยนะคะ น้องยินดีช่วยเหลือค่ะ"
   - English: "Hello! I'm I-SAVE Chatbot. Feel free to ask me anything about the I-SAVE system. I'm happy to help!"
   - คำถามเช่น "มีอะไรบ้าง", "ดูข้อมูล", "มีข้อมูลอะไร" ไม่ใช่การทักทาย → ให้ถือว่าถามภาพรวม I-SAVE แล้วตอบตามข้อ 12
9. FIRST check: does the message relate to any of these I-SAVE topics?
   → items / item codes / item plan / แผน item / ข้อมูล item
   → machine groups / เครื่องจักร / เครื่องทอ / ข้อมูลเครื่อง
   → machine capacity / กำลังการผลิต / เครื่องว่าง / capacity
   → booking / การจอง / ข้อมูลการจอง
   → knit plan / แผนทอ / แผนการทอ / ข้อมูลแผนทอ / แผนการผลิต
   → KP Weight / week / YW / gauge
   If YES → ALWAYS call the appropriate tool. Even if no item/group/week is specified, still call the tool with no filter and give an overview per rule 12. NEVER reject an I-SAVE topic.
   If the message is clearly unrelated to I-SAVE (e.g. weather, cooking, today's date, general knowledge) → reply with this only (no extra text):
   - Thai: "ขออภัยค่ะ น้อง I-SAVE Chatbot ยังไม่สามารถตอบคำถามนี้ได้ในขณะนี้\nรบกวนพี่ๆ สอบถามเฉพาะข้อมูลที่เกี่ยวข้องกับระบบ I-SAVE หรือหัวข้อที่น้องรองรับนะคะ"
   - English: "Sorry, I'm unable to answer this question. Please ask only about I-SAVE system data or supported topics."
10. Week terminology: Thai responses → always use "สัปดาห์" (e.g. "สัปดาห์ที่ 22") — never "week 22" or "วีค 22". English responses → use "week" (e.g. "Week 22").
    Gauge terminology: always write "Gauge" or abbreviate as "G" (e.g. "24G", "28G") — never use "เกจ" in any language.
11. When multiple machine groups have available capacity, give a summary first:
    - Thai: "มีเครื่องว่างรวม **XX เครื่อง** ใน YY กลุ่ม" แล้วถามว่า "ต้องการดูรายละเอียดแต่ละกลุ่มเพิ่มเติมไหมคะ"
    - English: "Total **XX machines** available across YY groups. Would you like details per group?"
12. If no Item or group is specified, give an overview:
    - Thai: "พบ Item ในแผนทั้งหมด [จำนวน] รายการ อยู่ใน [จำนวน] กลุ่มเครื่อง เช่น [รายชื่อกลุ่มหลัก]\nKP_Weight รวม [ยอดรวม] ตัน\nต้องการดูรายละเอียดเพิ่มเติมไหมคะ เช่น Item, กลุ่มเครื่อง, Gauge หรือช่วงสัปดาห์"
    - English: "Found [count] items in the plan across [count] machine groups (e.g. [main groups]).\nTotal KP_Weight: [total] tons.\nWould you like more details by item, group, Gauge, or week range?"
13. If item code is partial and matches more than 1 result, show a numbered list (1, 2, 3, 4) and ask which one the user wants before showing details.
14. When asked about a specific item, call get_item_plan first, then format the response using ACTUAL values from the tool result.
    CRITICAL: NEVER output literal bracket placeholders. Replace every placeholder with real data. If tool returns no data, say item was not found.
    Format template (replace ALL bracketed parts with real values from tool result):
    - Thai: "Item {{actual_item_code}} สามารถทอได้ที่กลุ่มเครื่อง {{actual_group_name}} โดยมีรายละเอียดแผนทอ ดังนี้\n1.สัปดาห์ที่ {{actual_YW}} จำนวน {{actual_KP_Weight}} ตัน\n...\nหากต้องการสอบถามเรื่องไหนเพิ่มเติม สามารถพิมพ์สอบถามได้เลยค่ะ"
    - English: "Item {{actual_item_code}} can be knitted at machine group {{actual_group_name}}. Knitting plan details:\n1. Week {{actual_YW}}: {{actual_KP_Weight}} tons\n...\nFeel free to ask if you need more information."
    - Always convert KP_Weight from kg to tons (divide by 1000) and display with "ตัน" (Thai) or "tons" (English). E.g. 859739 kg → 859.74 ตัน
    - If item spans multiple groups, list each group separately"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_item_plan",
            "description": (
                "ดึงข้อมูล Item Plan จาก BookingMaster: "
                "Item=รหัสสินค้า, Group=กลุ่มเครื่อง, KP_Weight=น้ำหนักที่วางแผน (kg), YW=สัปดาห์. "
                "ใช้ตอบคำถามเกี่ยวกับ item plan, กลุ่มเครื่องของ item, KP Weight, สัปดาห์ที่จะทอ"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_code": {
                        "type": "string",
                        "description": "รหัส item เช่น F100114/10A0 ถ้าไม่ระบุจะคืนทุก item"
                    },
                    "group": {
                        "type": "string",
                        "description": "กรองเฉพาะกลุ่มเครื่อง เช่น SKP, SKPLE, SKPTA"
                    },
                    "week": {
                        "type": "string",
                        "description": "กรองเฉพาะสัปดาห์ เช่น week22, wk22, 202622"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_machine_capacity",
            "description": (
                "ดึงข้อมูลกำลังการผลิต Table_MC: "
                "YW=สัปดาห์, Group=กลุ่มเครื่อง, Guage=gauge (column name in DB is misspelled), "
                "Total=เครื่องทั้งหมด, Used_N=ใช้ Normal, Used_F=ใช้ FQC, Ava=เครื่องว่าง. "
                "ใช้ตอบคำถามเรื่องเครื่องว่าง, กำลังการผลิต, เครื่องทั้งหมดในกลุ่ม"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "description": "กลุ่มเครื่อง เช่น SKP, SKPLE, SKPTA ถ้าไม่ระบุจะคืนทุกกลุ่ม"
                    },
                    "week": {
                        "type": "string",
                        "description": "สัปดาห์ เช่น week22, wk22, 202622 ถ้าไม่ระบุจะคืนทุกสัปดาห์"
                    },
                    "gauge": {
                        "type": "string",
                        "description": "Gauge ของเครื่อง เช่น 20, 24, 28 ถ้าไม่ระบุจะคืนทุก gauge"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_booking",
            "description": (
                "ดึงข้อมูล Booking Master: "
                "YW=สัปดาห์, MC_GROUP=กลุ่มเครื่อง, Used=จำนวนเครื่องที่จองแล้ว. "
                "ใช้ตอบคำถามเรื่องการจองเครื่อง"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "group": {
                        "type": "string",
                        "description": "กลุ่มเครื่อง ถ้าไม่ระบุจะคืนทุกกลุ่ม"
                    },
                    "week": {
                        "type": "string",
                        "description": "สัปดาห์ ถ้าไม่ระบุจะคืนทุกสัปดาห์"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_knit_plan",
            "description": (
                "ดึงแผนการทอ (Knit Plan): "
                "Item=รหัสสินค้า, Group=กลุ่มเครื่อง, KP_Weight=น้ำหนัก (kg), YW=สัปดาห์. "
                "ใช้ตอบคำถามเรื่องแผนการทอ รายการสินค้าในแต่ละสัปดาห์"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "week": {
                        "type": "string",
                        "description": "สัปดาห์ ถ้าไม่ระบุจะคืนทุกสัปดาห์"
                    },
                    "group": {
                        "type": "string",
                        "description": "กลุ่มเครื่อง ถ้าไม่ระบุจะคืนทุกกลุ่ม"
                    },
                    "item_code": {
                        "type": "string",
                        "description": "รหัส item ถ้าไม่ระบุจะคืนทุก item"
                    }
                },
                "required": []
            }
        }
    }
]


class ResponseProcessor:
    def __init__(self):
        self._openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _build_history_messages(self, conversation_history: list, limit: int = 6) -> list:
        messages = []
        recent = conversation_history[-(limit + 1):-1] if len(conversation_history) > 1 else []
        for msg in recent:
            role = msg.get('sender') or msg.get('role') or msg.get('message_type', '')
            content = msg.get('content') or msg.get('message', '')
            if not content:
                continue
            if role == 'user':
                messages.append({"role": "user", "content": content})
            elif role in ('assistant', 'ai'):
                messages.append({"role": "assistant", "content": content})
        return messages

    # ---- Tool implementations ----

    def _tool_get_item_plan(self, item_code: str = None, group: str = None, week: str = None) -> str:
        cached, ready = get_data_cache().get('query_item')
        if not ready or not cached:
            return "ข้อมูล Item Plan ยังไม่พร้อม กรุณาลองใหม่อีกครั้ง"
        data = cached.get('data', '')
        if not data:
            return "ไม่มีข้อมูล Item Plan"

        lines = data.splitlines()
        header = lines[0]
        # columns: Item,Group,KP_Weight,YW

        yw_filter = None
        if week:
            yws = _week_keyword_to_yw(week)
            yw_filter = yws[0] if yws else (week if re.match(r'^\d{6}$', week) else None)

        result = []
        for line in lines[1:]:
            cols = line.split(',')
            if not cols:
                continue
            item_col = cols[0].strip().upper() if len(cols) > 0 else ''
            group_col = cols[1].strip().lower() if len(cols) > 1 else ''
            yw_col = cols[3].strip() if len(cols) > 3 else ''

            if item_code and item_col != item_code.upper():
                continue
            if group and not _group_matches(group_col, [group.lower()]):
                continue
            if yw_filter and yw_col != yw_filter:
                continue
            result.append(line)

        if result:
            min_yw = _min_plannable_yw()
            if yw_filter and yw_filter < min_yw:
                note = f"[หมายเหตุ: YW {yw_filter} ผ่านมาแล้ว สัปดาห์เร็วที่สุดที่วางแผนได้ = YW {min_yw}]\n"
            else:
                past = [l for l in result if len(l.split(',')) > 3 and l.split(',')[3].strip() < min_yw]
                note = f"[หมายเหตุ: มี {len(past)} รายการที่อยู่ใน YW ที่ผ่านมาแล้ว (ก่อน YW {min_yw})]\n" if past else ""
            total_kg = 0.0
            for l in result:
                cols = l.split(',')
                if len(cols) > 2:
                    try:
                        total_kg += float(cols[2].strip())
                    except ValueError:
                        pass
            footer = f"[TOTAL_KP_WEIGHT={total_kg:.2f} kg = {total_kg/1000:.4f} ตัน — ใช้ค่านี้เท่านั้น ห้ามคำนวณเอง]\n"
            return note + header + '\n' + '\n'.join(result) + '\n' + footer
        if item_code:
            return f"ไม่พบ item {item_code} ใน Item Plan"
        return "ไม่พบข้อมูลที่ตรงกับเงื่อนไข"

    def _tool_get_machine_capacity(self, group: str = None, week: str = None, gauge: str = None) -> str:
        cached, ready = get_data_cache().get('query_cap_ava')
        if not ready or not cached:
            return "ข้อมูลกำลังการผลิตยังไม่พร้อม กรุณาลองใหม่อีกครั้ง"
        data = cached.get('data', {})
        csv_text = data.get('mc', '') if isinstance(data, dict) else ''
        if not csv_text:
            return "ไม่มีข้อมูล Machine Capacity"

        lines = csv_text.splitlines()
        header = lines[0]
        # columns: YW,Group,Guage,Total,Used_N,Used_F,Ava

        yw_filter = None
        if week:
            yws = _week_keyword_to_yw(week)
            yw_filter = yws[0] if yws else (week if re.match(r'^\d{6}$', week) else None)

        result = []
        for line in lines[1:]:
            cols = line.split(',')
            if not cols:
                continue
            yw_col = cols[0].strip() if len(cols) > 0 else ''
            group_col = cols[1].strip().lower() if len(cols) > 1 else ''
            gauge_col = cols[2].strip() if len(cols) > 2 else ''

            if yw_filter and yw_col != yw_filter:
                continue
            if group and not _group_matches(group_col, [group.lower()]):
                continue
            if gauge and gauge_col != gauge:
                continue
            result.append(line)

        if result:
            min_yw = _min_plannable_yw()
            note = f"[หมายเหตุ: week เร็วที่สุดที่วางแผนได้ = YW {min_yw}]\n"
            return note + header + '\n' + '\n'.join(result)
        return f"ไม่พบข้อมูล Machine Capacity (group={group}, week={week}, gauge={gauge})"

    def _tool_get_booking(self, group: str = None, week: str = None) -> str:
        cached, ready = get_data_cache().get('query_booking')
        if not ready or not cached:
            return "ข้อมูล Booking ยังไม่พร้อม กรุณาลองใหม่อีกครั้ง"
        data = cached.get('data', '')
        if not data:
            return "ไม่มีข้อมูล Booking"

        lines = data.splitlines()
        header = lines[0]
        # columns: YW,MC_GROUP,Used

        yw_filter = None
        if week:
            yws = _week_keyword_to_yw(week)
            yw_filter = yws[0] if yws else (week if re.match(r'^\d{6}$', week) else None)

        result = []
        for line in lines[1:]:
            cols = line.split(',')
            if not cols:
                continue
            yw_col = cols[0].strip() if len(cols) > 0 else ''
            group_col = cols[1].strip().lower() if len(cols) > 1 else ''

            if yw_filter and yw_col != yw_filter:
                continue
            if group and not _group_matches(group_col, [group.lower()]):
                continue
            result.append(line)

        if result:
            return header + '\n' + '\n'.join(result)
        return f"ไม่พบข้อมูล Booking (group={group}, week={week})"

    def _tool_get_knit_plan(self, week: str = None, group: str = None, item_code: str = None) -> str:
        return self._tool_get_item_plan(item_code=item_code, group=group, week=week)

    def _execute_tool_call(self, tool_call) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except Exception:
            args = {}
        logger.info(f"Tool call: {name}({args})")

        if name == "get_item_plan":
            return self._tool_get_item_plan(
                item_code=args.get("item_code"),
                group=args.get("group"),
                week=args.get("week"),
            )
        elif name == "get_machine_capacity":
            return self._tool_get_machine_capacity(
                group=args.get("group"),
                week=args.get("week"),
                gauge=args.get("gauge"),
            )
        elif name == "get_booking":
            return self._tool_get_booking(
                group=args.get("group"),
                week=args.get("week"),
            )
        elif name == "get_knit_plan":
            return self._tool_get_knit_plan(
                week=args.get("week"),
                group=args.get("group"),
                item_code=args.get("item_code"),
            )
        return f"ไม่รู้จัก tool: {name}"

    _MACHINE_INFO_REPLY = (
        "ตอนนี้น้อง I-SAVE Chatbot ยังไม่รู้เลยว่าพี่ๆ ต้องการดูข้อมูลเครื่องจักรส่วนไหนค่ะ เช่น\n"
        "• เครื่องว่าง (Ava) ตามสัปดาห์\n"
        "• กำลังการผลิตรวมของแต่ละกลุ่มเครื่อง\n"
        "• การจองเครื่องของแต่ละกลุ่ม / สัปดาห์\n"
        "• หรือข้อมูลของกลุ่มเครื่องใดกลุ่มหนึ่ง (เช่น SKP, SKPLE, SKPTA)\n"
        "รบกวนพิมพ์เพิ่มให้หน่อยนะคะว่าอยากดู\n"
        "1) กลุ่มเครื่องอะไร (ถ้ามี) และ\n"
        "2) สัปดาห์ไหน (เช่น 202624 หรือ ช่วงสัปดาห์ 202624–202626)\n"
        "แล้วน้องจะดึงข้อมูลจากระบบ I-SAVE ให้ทันทีค่ะ"
    )

    _CAPACITY_INFO_REPLY = (
        "ขออภัยค่ะ ข้อมูล Capacity ยังไม่พร้อมในขณะนี้\n"
        "กรุณารอสักครู่แล้วลองใหม่อีกครั้ง หรือติดต่อผู้ดูแลระบบหากปัญหายังคงอยู่ค่ะ"
    )

    def _get_machine_capacity_suggestions(self) -> list:
        cached, ready = get_data_cache().get('query_cap_ava')
        if not ready or not cached:
            return ['เครื่องว่าง SKP สัปดาห์นี้', 'กำลังการผลิตรวม', 'การจองเครื่อง', 'ดูแผนทอ']
        data = cached.get('data', {})
        mc_csv = data.get('mc', '') if isinstance(data, dict) else ''
        if not mc_csv:
            return ['เครื่องว่าง SKP สัปดาห์นี้', 'กำลังการผลิตรวม', 'การจองเครื่อง', 'ดูแผนทอ']

        min_yw = _min_plannable_yw()
        rows = []
        for line in mc_csv.splitlines()[1:]:
            cols = line.split(',')
            if len(cols) >= 7:
                try:
                    rows.append({
                        'yw': cols[0].strip(),
                        'group': cols[1].strip(),
                        'total': float(cols[3]) if cols[3].strip() else 0,
                        'ava': float(cols[6]) if cols[6].strip() else 0,
                    })
                except ValueError:
                    pass

        snapshot_rows = [r for r in rows if r['yw'] == min_yw]
        if not snapshot_rows:
            future = [r for r in rows if r['yw'] >= min_yw]
            if future:
                first_yw = min(r['yw'] for r in future)
                snapshot_rows = [r for r in rows if r['yw'] == first_yw]
        if not snapshot_rows:
            return ['เครื่องว่าง SKP สัปดาห์นี้', 'กำลังการผลิตรวม', 'การจองเครื่อง', 'ดูแผนทอ']

        snapshot_yw = snapshot_rows[0]['yw']
        try:
            week_num = int(snapshot_yw[4:]) if len(snapshot_yw) == 6 else int(snapshot_yw)
        except ValueError:
            week_num = 0

        group_ava: dict = {}
        for r in snapshot_rows:
            group_ava[r['group']] = group_ava.get(r['group'], 0) + r['ava']

        sorted_groups = sorted(group_ava, key=lambda g: group_ava[g], reverse=True)
        suggestions = []
        for g in sorted_groups[:2]:
            suggestions.append(f"Capacity กลุ่ม {g} สัปดาห์ที่ {week_num}")
        suggestions.append(f"เครื่องว่างทุกกลุ่ม สัปดาห์ที่ {week_num}")
        suggestions.append("การจองเครื่องทั้งหมด")
        return suggestions[:4]

    def _build_machine_capacity_overview(self) -> str:
        cached, ready = get_data_cache().get('query_cap_ava')
        if not ready or not cached:
            return self._MACHINE_INFO_REPLY

        data = cached.get('data', {})
        mc_csv = data.get('mc', '') if isinstance(data, dict) else ''
        if not mc_csv:
            return self._MACHINE_INFO_REPLY

        lines = mc_csv.splitlines()
        # columns: YW,Group,Guage,Total,Used_N,Used_F,Ava

        rows = []
        for line in lines[1:]:
            cols = line.split(',')
            if len(cols) < 7:
                continue
            try:
                rows.append({
                    'yw': cols[0].strip(),
                    'group': cols[1].strip(),
                    'guage': cols[2].strip(),
                    'total': float(cols[3]) if cols[3].strip() else 0,
                    'used_n': float(cols[4]) if cols[4].strip() else 0,
                    'used_f': float(cols[5]) if cols[5].strip() else 0,
                    'ava': float(cols[6]) if cols[6].strip() else 0,
                })
            except ValueError:
                continue

        if not rows:
            return self._MACHINE_INFO_REPLY

        min_yw = _min_plannable_yw()

        # Use nearest plannable week as snapshot
        snapshot_rows = [r for r in rows if r['yw'] == min_yw]
        if not snapshot_rows:
            future_rows = [r for r in rows if r['yw'] >= min_yw]
            if future_rows:
                first_yw = min(r['yw'] for r in future_rows)
                snapshot_rows = [r for r in rows if r['yw'] == first_yw]
        if not snapshot_rows:
            snapshot_rows = rows

        snapshot_yw = snapshot_rows[0]['yw'] if snapshot_rows else min_yw
        try:
            week_num = int(snapshot_yw[4:]) if len(snapshot_yw) == 6 else int(snapshot_yw)
        except ValueError:
            week_num = 0

        # Distinct main groups and sub-groups across all data
        all_groups = set(r['group'] for r in rows if r['group'])
        all_subgroups = set((r['group'], r['guage']) for r in rows if r['group'])

        # Aggregate by group for snapshot week
        group_total: dict = {}
        group_ava: dict = {}
        for r in snapshot_rows:
            g = r['group']
            group_total[g] = group_total.get(g, 0) + r['total']
            group_ava[g] = group_ava.get(g, 0) + r['ava']

        total_machines = sum(group_total.values())
        total_ava = sum(group_ava.values())

        group_util = {
            g: (group_total[g] - group_ava.get(g, 0)) / group_total[g]
            for g in group_total if group_total[g] > 0
        }

        max_machines_group = max(group_total, key=lambda g: group_total[g]) if group_total else '-'
        tightest_group = max(group_util, key=lambda g: group_util[g]) if group_util else '-'

        # KP Weight total from item plan for snapshot week
        total_kg = 0.0
        item_cached, item_ready = get_data_cache().get('query_item')
        if item_ready and item_cached:
            item_data = item_cached.get('data', '')
            for item_line in item_data.splitlines()[1:]:
                item_cols = item_line.split(',')
                if len(item_cols) >= 4 and item_cols[3].strip() == snapshot_yw:
                    try:
                        total_kg += float(item_cols[2].strip())
                    except ValueError:
                        pass

        n_main = len(all_groups)
        n_sub = len(all_subgroups)
        tightest_util_pct = round(group_util.get(tightest_group, 0) * 100)
        tightest_ava = int(group_ava.get(tightest_group, 0))

        out_lines = [
            f"ภาพรวม Machine Capacity สัปดาห์ที่ {week_num}",
            f"มีเครื่องทั้งหมด **{int(total_machines)} เครื่อง** แบ่งเป็น **{n_main} กลุ่มเครื่องหลัก** และ **{n_sub} กลุ่มย่อย** ค่ะ",
        ]
        if total_kg > 0:
            out_lines.append(f"KP Weight รวมสัปดาห์นี้อยู่ที่ประมาณ **{total_kg/1000:.2f} ตัน**")
        out_lines.append(
            f"กลุ่มที่มีเครื่องมากที่สุดคือ **{max_machines_group}** ({int(group_total.get(max_machines_group, 0))} เครื่อง)"
        )
        if tightest_group and tightest_group != '-':
            out_lines.append(
                f"กลุ่มที่ Capacity ค่อนข้างตึงคือ **{tightest_group}** "
                f"(ใช้ไปแล้ว {tightest_util_pct}% เครื่องว่าง {tightest_ava} เครื่อง)"
            )
        out_lines.append(f"เครื่องว่างรวม **{int(total_ava)} เครื่อง** จาก {int(total_machines)} เครื่องทั้งหมด")
        out_lines.append("ถ้าต้องการดูรายละเอียดเพิ่มเติม สามารถเลือกกลุ่มเครื่อง หรือระบุสัปดาห์ที่ต้องการได้เลยค่ะ")

        return '\n'.join(out_lines)


    def _parse_mc_snapshot(self):
        """Return (snapshot_rows, snapshot_yw, week_num, group_total, group_used, group_ava) or None if no data."""
        cached, ready = get_data_cache().get('query_cap_ava')
        if not ready or not cached:
            return None
        data = cached.get('data', {})
        mc_csv = data.get('mc', '') if isinstance(data, dict) else ''
        if not mc_csv:
            return None

        min_yw = _min_plannable_yw()
        rows = []
        for line in mc_csv.splitlines()[1:]:
            cols = line.split(',')
            if len(cols) < 7:
                continue
            try:
                rows.append({
                    'yw': cols[0].strip(), 'group': cols[1].strip(),
                    'total': float(cols[3]) if cols[3].strip() else 0,
                    'used_n': float(cols[4]) if cols[4].strip() else 0,
                    'used_f': float(cols[5]) if cols[5].strip() else 0,
                    'ava': float(cols[6]) if cols[6].strip() else 0,
                })
            except ValueError:
                continue
        if not rows:
            return None

        snap = [r for r in rows if r['yw'] == min_yw]
        if not snap:
            future = [r for r in rows if r['yw'] >= min_yw]
            if future:
                first_yw = min(r['yw'] for r in future)
                snap = [r for r in rows if r['yw'] == first_yw]
        if not snap:
            snap = rows

        snapshot_yw = snap[0]['yw']
        try:
            week_num = int(snapshot_yw[4:]) if len(snapshot_yw) == 6 else int(snapshot_yw)
        except ValueError:
            week_num = 0

        group_total: dict = {}
        group_used: dict = {}
        group_ava: dict = {}
        for r in snap:
            g = r['group']
            group_total[g] = group_total.get(g, 0) + r['total']
            group_used[g] = group_used.get(g, 0) + r['used_n'] + r['used_f']
            group_ava[g] = group_ava.get(g, 0) + r['ava']

        return snap, snapshot_yw, week_num, group_total, group_used, group_ava

    def _build_capacity_overview(self) -> str:
        parsed = self._parse_mc_snapshot()
        if not parsed:
            return self._CAPACITY_INFO_REPLY

        _, snapshot_yw, week_num, group_total, group_used, group_ava = parsed

        total_machines = sum(group_total.values())
        total_used = sum(group_used.values())
        total_ava = sum(group_ava.values())
        util_pct = (total_used / total_machines * 100) if total_machines > 0 else 0
        n_groups = len(group_total)
        min_yw = _min_plannable_yw()

        # KP Weight: sum across ALL plannable weeks = total planned load
        total_kp_all = 0.0
        snapshot_kp = 0.0
        item_cached, item_ready = get_data_cache().get('query_item')
        if item_ready and item_cached:
            item_data = item_cached.get('data', '')
            for item_line in item_data.splitlines()[1:]:
                cols = item_line.split(',')
                if len(cols) < 4:
                    continue
                yw_col = cols[3].strip()
                kp_raw = cols[2].strip()
                if yw_col >= min_yw and kp_raw:
                    try:
                        kp = float(kp_raw)
                        total_kp_all += kp
                        if yw_col == snapshot_yw:
                            snapshot_kp += kp
                    except ValueError:
                        pass

        remaining_kp = total_kp_all - snapshot_kp

        # Per-group utilization %
        group_util_pct = {
            g: (group_used[g] / group_total[g] * 100) if group_total.get(g, 0) > 0 else 0
            for g in group_total
        }
        highest_util_group = max(group_util_pct, key=lambda g: group_util_pct[g]) if group_util_pct else '-'
        most_ava_group = max(group_ava, key=lambda g: group_ava[g]) if group_ava else '-'
        critical_threshold = 85.0
        critical = {g: u for g, u in group_util_pct.items() if u > critical_threshold}
        critical_group = max(critical, key=lambda g: critical[g]) if critical else None

        out = [
            f"ตอนนี้ข้อมูล Capacity ในระบบครอบคลุมตั้งแต่สัปดาห์ที่ **{week_num}** เป็นต้นไป",
            "",
            "**ภาพรวม Capacity ทั้งหมด**",
            f"- จำนวนกลุ่มเครื่องที่มีข้อมูล Capacity : **{n_groups} กลุ่ม**",
        ]
        if total_kp_all > 0:
            out.append(f"- Capacity รวมทั้งหมด (KP Weight ทุกสัปดาห์) : **{total_kp_all/1000:.2f} ตัน**")
            out.append(f"- ใช้งานไปแล้ว (สัปดาห์ที่ {week_num}) : **{snapshot_kp/1000:.2f} ตัน**")
            out.append(f"- Capacity คงเหลือในแผน : **{remaining_kp/1000:.2f} ตัน**")
        out += [
            f"- เครื่องทั้งหมด : **{int(total_machines)} เครื่อง** | ใช้งาน **{int(total_used)}** | ว่าง **{int(total_ava)}**",
            f"- % การใช้ Capacity เฉลี่ย : **{round(util_pct, 1)}%**",
            "",
            "จากภาพรวมตอนนี้",
        ]
        if highest_util_group != '-':
            out.append(f"กลุ่มที่ใช้ Capacity สูงที่สุดคือ **{highest_util_group}** (ใช้งาน {round(group_util_pct[highest_util_group], 1)}%)")
        if most_ava_group != '-':
            out.append(f"กลุ่มที่ยังมี Capacity เหลือมากที่สุดคือ **{most_ava_group}** ({int(group_ava[most_ava_group])} เครื่องว่าง)")
        if critical_group:
            out.append(f"และกลุ่มที่ควรติดตามใกล้ชิดคือ **{critical_group}** เพราะมีการใช้ Capacity เกิน {round(critical[critical_group], 1)}%")
        out.append("ถ้าต้องการดูรายละเอียดเพิ่มเติม สามารถระบุกลุ่มเครื่องหรือสัปดาห์ที่ต้องการได้เลยค่ะ")
        return '\n'.join(out)

    def _get_capacity_suggestions(self) -> list:
        parsed = self._parse_mc_snapshot()
        if not parsed:
            return ['ขอดู Capacity กลุ่ม SKP', 'เครื่องว่างรวมทุกกลุ่ม', 'การจองเครื่อง', 'ดูแผนทอ']

        _, _, week_num, group_total, group_used, _ = parsed
        group_util_pct = {
            g: (group_used[g] / group_total[g] * 100) if group_total.get(g, 0) > 0 else 0
            for g in group_total
        }
        # Top 2 by utilization — most actionable groups
        top2 = sorted(group_util_pct, key=lambda g: group_util_pct[g], reverse=True)[:2]
        suggestions = [f"Capacity กลุ่ม {g} สัปดาห์ที่ {week_num}" for g in top2]
        suggestions.append(f"เครื่องว่างทุกกลุ่ม สัปดาห์ที่ {week_num}")
        suggestions.append("KP Weight รวมทุกกลุ่ม")
        return suggestions[:4]

    def _build_item_overview(self) -> str:
        item_cached, item_ready = get_data_cache().get('query_item')
        if not item_ready or not item_cached:
            return "ข้อมูล Item Plan ยังไม่พร้อม กรุณาลองใหม่อีกครั้งค่ะ"
        item_data = item_cached.get('data', '')
        if not item_data:
            return "ไม่มีข้อมูล Item Plan ในระบบค่ะ"

        min_yw = _min_plannable_yw()
        distinct_items: set = set()
        distinct_groups: set = set()
        distinct_weeks: set = set()
        total_kp = 0.0

        for line in item_data.splitlines()[1:]:
            cols = line.split(',')
            if len(cols) < 4:
                continue
            item_code = cols[0].strip()
            group = cols[1].strip()
            yw = cols[3].strip()
            if not item_code or not yw or yw < min_yw:
                continue
            try:
                kp = float(cols[2].strip()) if cols[2].strip() else 0.0
            except ValueError:
                kp = 0.0
            distinct_items.add(item_code)
            distinct_groups.add(group)
            distinct_weeks.add(yw)
            total_kp += kp

        if not distinct_items:
            return "ไม่พบข้อมูล Item Plan ในช่วงสัปดาห์ที่วางแผนได้ค่ะ"

        min_week_yw = min(distinct_weeks)
        try:
            min_week_num = int(min_week_yw[4:]) if len(min_week_yw) == 6 else int(min_week_yw)
        except ValueError:
            min_week_num = 0

        out = [
            f"ตอนนี้ระบบมีข้อมูล Item Plan ทั้งหมด **{len(distinct_items)} Item**",
            f"ครอบคลุมตั้งแต่สัปดาห์ที่ **{min_week_num}** เป็นต้นไป",
            "",
            "**ภาพรวม Item**",
            f"- จำนวน Item ที่มีแผนทอ : **{len(distinct_items)} Item**",
            f"- น้ำหนักรวมทั้งหมด : **{total_kp/1000:.2f} ตัน**",
            f"- จำนวนกลุ่มเครื่องที่เกี่ยวข้อง : **{len(distinct_groups)} กลุ่ม**",
            f"- จำนวนสัปดาห์ในแผน : **{len(distinct_weeks)} สัปดาห์**",
            "",
            'ถ้าต้องการดูละเอียดขึ้น สามารถระบุรหัส Item, กลุ่มเครื่อง หรือสัปดาห์ได้เลยค่ะ',
            'เช่น "ขอดู Item F100114/10A0" หรือ "Item ในกลุ่ม SKP สัปดาห์ที่ ' + str(min_week_num) + '"',
        ]
        return '\n'.join(out)

    def _get_item_suggestions(self) -> list:
        item_cached, item_ready = get_data_cache().get('query_item')
        if not item_ready or not item_cached:
            return ['ดู Item ในกลุ่ม SKP', 'ดูแผนทอ Item', 'ดูเครื่องว่าง', 'ข้อมูลแผนทอ']

        item_data = item_cached.get('data', '')
        min_yw = _min_plannable_yw()

        group_items: dict = {}
        min_week_yw = None
        for line in item_data.splitlines()[1:]:
            cols = line.split(',')
            if len(cols) < 4:
                continue
            item_code = cols[0].strip()
            group = cols[1].strip()
            yw = cols[3].strip()
            if not item_code or not yw or yw < min_yw:
                continue
            group_items.setdefault(group, set()).add(item_code)
            if min_week_yw is None or yw < min_week_yw:
                min_week_yw = yw

        if not group_items:
            return ['ดู Item ในกลุ่ม SKP', 'ดูแผนทอ Item', 'ดูเครื่องว่าง', 'ข้อมูลแผนทอ']

        try:
            min_w = int(min_week_yw[4:]) if min_week_yw and len(min_week_yw) == 6 else 0
        except ValueError:
            min_w = 0

        top_groups = sorted(group_items, key=lambda g: len(group_items[g]), reverse=True)[:2]
        suggestions = [f"Item ในกลุ่ม {g}" for g in top_groups]
        if min_w:
            suggestions.append(f"Item ทั้งหมดสัปดาห์ที่ {min_w}")
        suggestions.append("น้ำหนัก KP Weight ของ Item")
        return suggestions[:4]

    def _build_knit_plan_overview(self) -> str:
        item_cached, item_ready = get_data_cache().get('query_item')
        if not item_ready or not item_cached:
            return "ข้อมูลแผนทอยังไม่พร้อม กรุณาลองใหม่อีกครั้งค่ะ"
        item_data = item_cached.get('data', '')
        if not item_data:
            return "ไม่มีข้อมูลแผนทอในระบบค่ะ"

        min_yw = _min_plannable_yw()
        rows = []
        for line in item_data.splitlines()[1:]:
            cols = line.split(',')
            if len(cols) < 4:
                continue
            item_code = cols[0].strip()
            group = cols[1].strip()
            yw = cols[3].strip()
            if not item_code or not yw or yw < min_yw:
                continue
            try:
                kp = float(cols[2].strip()) if cols[2].strip() else 0.0
            except ValueError:
                kp = 0.0
            rows.append({'item': item_code, 'group': group, 'kp': kp, 'yw': yw})

        if not rows:
            return "ไม่พบข้อมูลแผนทอในช่วงสัปดาห์ที่วางแผนได้ค่ะ"

        total_records = len(rows)
        distinct_items = set(r['item'] for r in rows)
        distinct_groups = set(r['group'] for r in rows)
        distinct_weeks = set(r['yw'] for r in rows)
        total_kp = sum(r['kp'] for r in rows)

        min_week_in_data = min(distinct_weeks)
        max_week_in_data = max(distinct_weeks)
        try:
            min_w = int(min_week_in_data[4:]) if len(min_week_in_data) == 6 else int(min_week_in_data)
            max_w = int(max_week_in_data[4:]) if len(max_week_in_data) == 6 else int(max_week_in_data)
        except ValueError:
            min_w, max_w = 0, 0

        # Per-group aggregation
        group_items: dict = {}
        group_kp: dict = {}
        for r in rows:
            g = r['group']
            group_items.setdefault(g, set()).add(r['item'])
            group_kp[g] = group_kp.get(g, 0.0) + r['kp']

        # Per-week aggregation
        week_kp: dict = {}
        for r in rows:
            week_kp[r['yw']] = week_kp.get(r['yw'], 0.0) + r['kp']

        top_group = max(group_kp, key=lambda g: group_kp[g]) if group_kp else '-'
        busiest_yw = max(week_kp, key=lambda w: week_kp[w]) if week_kp else '-'
        try:
            busiest_week_num = int(busiest_yw[4:]) if len(busiest_yw) == 6 else int(busiest_yw)
        except ValueError:
            busiest_week_num = 0

        # Sort groups by KP_Weight descending
        sorted_groups = sorted(group_kp.keys(), key=lambda g: group_kp[g], reverse=True)

        out = [
            f"ตอนนี้ระบบมีข้อมูลแผนทอทั้งหมด **{total_records:,} รายการ**",
            f"ครอบคลุมตั้งแต่สัปดาห์ที่ **{min_w}** ถึง **{max_w}** ({len(distinct_weeks)} สัปดาห์)",
            "",
            "**ภาพรวมแผนทอ**",
            f"- จำนวน Item ในแผนทั้งหมด : **{len(distinct_items)} Item**",
            f"- น้ำหนักแผนทอรวม : **{total_kp/1000:.2f} ตัน**",
            f"- จำนวนกลุ่มเครื่องที่เกี่ยวข้อง : **{len(distinct_groups)} กลุ่ม**",
            "",
            "**สรุปตามกลุ่มเครื่องหลัก**",
        ]

        for g in sorted_groups[:6]:
            n_items = len(group_items[g])
            kp = int(group_kp[g])
            out.append(f"- **{g}** : {n_items} Item / {kp/1000:.2f} ตัน")

        out += [
            "",
            "จากภาพรวมตอนนี้",
            f"กลุ่มที่มีแผนทอมากที่สุดคือ **{top_group}** ({len(group_items.get(top_group, set()))} Item / {group_kp.get(top_group, 0)/1000:.2f} ตัน)",
            f"สัปดาห์ที่มีแผนทอหนักที่สุดคือ สัปดาห์ที่ **{busiest_week_num}** ({week_kp.get(busiest_yw, 0)/1000:.2f} ตัน)",
            "ถ้าต้องการดูรายละเอียดเพิ่มเติม สามารถระบุ Item, กลุ่มเครื่อง หรือสัปดาห์ที่ต้องการได้เลยค่ะ",
        ]
        return '\n'.join(out)

    def _get_knit_plan_suggestions(self) -> list:
        item_cached, item_ready = get_data_cache().get('query_item')
        if not item_ready or not item_cached:
            return ['แผนทอสัปดาห์นี้', 'ดูแผนทอกลุ่ม SKP', 'ดูเครื่องว่าง', 'ข้อมูล Item']

        item_data = item_cached.get('data', '')
        min_yw = _min_plannable_yw()

        group_kp: dict = {}
        week_kp: dict = {}
        for line in item_data.splitlines()[1:]:
            cols = line.split(',')
            if len(cols) < 4:
                continue
            yw = cols[3].strip()
            g = cols[1].strip()
            if not yw or yw < min_yw:
                continue
            try:
                kp = float(cols[2].strip()) if cols[2].strip() else 0.0
            except ValueError:
                kp = 0.0
            group_kp[g] = group_kp.get(g, 0.0) + kp
            week_kp[yw] = week_kp.get(yw, 0.0) + kp

        top_groups = sorted(group_kp, key=lambda g: group_kp[g], reverse=True)[:2]
        busiest_yw = max(week_kp, key=lambda w: week_kp[w]) if week_kp else None

        suggestions = [f"แผนทอกลุ่ม {g}" for g in top_groups]
        if busiest_yw:
            try:
                wn = int(busiest_yw[4:]) if len(busiest_yw) == 6 else int(busiest_yw)
                suggestions.append(f"แผนทอสัปดาห์ที่ {wn}")
            except ValueError:
                pass
        suggestions.append("ดูเครื่องว่างในแผนทอ")
        return suggestions[:4]

    async def process_message(
        self,
        user_message: str,
        username: str = 'คุณ',  # noqa: ARG002 — kept for API compatibility
        conversation_history: Optional[List[Dict]] = None,
    ) -> ProcessedResponse:
        if user_message.strip() == 'ข้อมูลเครื่องจักร':
            return ProcessedResponse(
                message=self._build_machine_capacity_overview(),
                response_type='text',
                processing_path='shortcut',
                metadata={'intent': 'machine_info_menu', 'confidence': 1.0, 'matched_keywords': []},
                suggestions=self._get_machine_capacity_suggestions(),
            )

        if user_message.strip() == 'ข้อมูล Capacity':
            return ProcessedResponse(
                message=self._build_capacity_overview(),
                response_type='text',
                processing_path='shortcut',
                metadata={'intent': 'capacity_menu', 'confidence': 1.0, 'matched_keywords': []},
                suggestions=self._get_capacity_suggestions(),
            )

        if user_message.strip() == 'ข้อมูลแผนทอ':
            return ProcessedResponse(
                message=self._build_knit_plan_overview(),
                response_type='text',
                processing_path='shortcut',
                metadata={'intent': 'knitting_plan', 'confidence': 1.0, 'matched_keywords': []},
                suggestions=self._get_knit_plan_suggestions(),
            )

        if user_message.strip() == 'ข้อมูล Item':
            return ProcessedResponse(
                message=self._build_item_overview(),
                response_type='text',
                processing_path='shortcut',
                metadata={'intent': 'item_data', 'confidence': 1.0, 'matched_keywords': []},
                suggestions=self._get_item_suggestions(),
            )

        history_msgs = self._build_history_messages(conversation_history or [])
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(min_yw=_min_plannable_yw())
        lang = _detect_reply_language(user_message, conversation_history)
        lang_instruction = "IMPORTANT: Reply in Thai language." if lang == 'thai' else "IMPORTANT: Reply in English."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": lang_instruction},
            *history_msgs,
            {"role": "user", "content": user_message},
        ]

        tool_calls_log: List[Dict] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        loop = asyncio.get_running_loop()

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = await loop.run_in_executor(
                    None,
                    lambda: self._openai.chat.completions.create(
                        model=self._model,
                        messages=messages,
                        tools=TOOLS,
                        tool_choice="auto",
                        max_completion_tokens=1500,
                    ),
                )
            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
                err_msg = f"Sorry, the AI system is temporarily unavailable. ({e})" if lang == 'english' else f"ขออภัยค่ะ ระบบ AI ขัดข้องชั่วคราว ({e})"
                return ProcessedResponse(
                    message=err_msg,
                    response_type='text',
                    metadata={'intent': 'error', 'confidence': 0.0, 'matched_keywords': []},
                )

            choice = response.choices[0]
            msg = choice.message
            if response.usage:
                total_prompt_tokens += response.usage.prompt_tokens
                total_completion_tokens += response.usage.completion_tokens

            if choice.finish_reason == "tool_calls" and msg.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                })
                for tool_call in msg.tool_calls:
                    result = self._execute_tool_call(tool_call)
                    tool_calls_log.append({
                        'tool': tool_call.function.name,
                        'args': tool_call.function.arguments,
                        'result_rows': len(result.splitlines()),
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
            else:
                fallback = "Sorry, I'm unable to respond." if lang == 'english' else "ขออภัยค่ะ ไม่สามารถตอบได้"
                return ProcessedResponse(
                    message=_clean_response(msg.content or fallback),
                    response_type='text',
                    processing_path='agent',
                    mcp_calls=tool_calls_log,
                    metadata={
                        'intent': 'agent',
                        'confidence': 1.0,
                        'matched_keywords': [c['tool'] for c in tool_calls_log],
                        'model': self._model,
                        'prompt_tokens': total_prompt_tokens,
                        'completion_tokens': total_completion_tokens,
                        'total_tokens': total_prompt_tokens + total_completion_tokens,
                    },
                    suggestions=self._get_suggestions(tool_calls_log, lang),
                )

        timeout_msg = "Sorry, the system took too long to respond. Please try again." if lang == 'english' else "ขออภัยค่ะ ระบบประมวลผลนานเกินไป กรุณาถามใหม่อีกครั้ง"
        return ProcessedResponse(
            message=timeout_msg,
            response_type='text',
            processing_path='agent',
            mcp_calls=tool_calls_log,
            metadata={'intent': 'agent', 'confidence': 0.0, 'matched_keywords': []},
        )

    def _get_suggestions(self, tool_calls_log: list, lang: str = 'thai') -> list:
        tools_used = {c['tool'] for c in tool_calls_log}
        if lang == 'english':
            if 'get_item_plan' in tools_used or 'get_knit_plan' in tools_used:
                return ['Check available machines for this item', 'View all KP Weights', 'View knit plan this week']
            if 'get_machine_capacity' in tools_used:
                return ['Check available machines next week', 'View booking', 'View knit plan']
            if 'get_booking' in tools_used:
                return ['Check available machines', 'View knit plan', 'View item plan']
            return ['Machine info', 'Item info', 'Capacity info']
        if 'get_item_plan' in tools_used or 'get_knit_plan' in tools_used:
            return ['ดูเครื่องว่างสำหรับ item นี้', 'ดู KP Weight ทั้งหมด', 'ดูแผนทอสัปดาห์นี้']
        if 'get_machine_capacity' in tools_used:
            return ['ดูเครื่องว่างสัปดาห์ถัดไป', 'ดูการจอง', 'ดูแผนทอ']
        if 'get_booking' in tools_used:
            return ['ดูเครื่องว่าง', 'ดูแผนทอ', 'ดู item plan']
        return ['ข้อมูลเครื่องจักร', 'ข้อมูล Item', 'ข้อมูล Capacity']


_response_processor_instance = None


def get_response_processor() -> ResponseProcessor:
    global _response_processor_instance
    if _response_processor_instance is None:
        _response_processor_instance = ResponseProcessor()
    return _response_processor_instance
