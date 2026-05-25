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
    _bullet_gap = re.compile(r'([ \t]*[-•*][^\n]+)\n\n([ \t]*[-•*])', re.MULTILINE)
    while _bullet_gap.search(text):
        text = _bullet_gap.sub(r'\1\n\2', text)
    return text.strip()


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
        r'\bw(\d{1,2})\b',
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

LANGUAGE RULE (highest priority): Always reply in the same language as the user's message.
- If the user writes in English → reply in English
- If the user writes in Thai → reply in Thai
- If mixed → follow the dominant language

คุณมี tools สำหรับดึงข้อมูลจากระบบ ให้เรียก tool ก่อนตอบทุกครั้งที่คำถามเกี่ยวกับข้อมูล:
- get_item_plan        : แผน item (กลุ่มเครื่อง, KP_Weight, สัปดาห์ที่วางแผน)
- get_machine_capacity : กำลังการผลิต (Total, Used_N, Used_F, Ava=available machines)
- get_booking          : การจองเครื่องต่อกลุ่มต่อสัปดาห์
- get_knit_plan        : แผนการทอ (item, กลุ่ม, KP_Weight ตามสัปดาห์)

กฎสำคัญ:
1. ตอบเฉพาะ message ปัจจุบันเท่านั้น — ห้าม re-fetch หรือแสดงข้อมูลจาก message ก่อนหน้าซ้ำ ถ้า message ใหม่ไม่ได้ถามเรื่องข้อมูล ห้ามเรียก tool เด็ดขาด
2. ถ้าคำถามเกี่ยวกับข้อมูลในระบบ ให้เรียก tool ก่อนเสมอ อย่าตอบจากความรู้ตัวเอง
3. ต้องการข้อมูลหลายอย่าง → เรียก tool ได้หลายครั้ง
4. YW = week code in format YYYYWW e.g. 202622 = year 2026 week 22
5. Earliest plannable week = YW {min_yw} (current +2 weeks) — exclude YW below this
6. Ava = available machines (Total − Used_N − Used_F)
7. Be concise. Use bold (**text**) for key numbers. No blank lines between bullet points.
8. เมื่อผู้ใช้ทักทาย (สวัสดี, hello, hi ฯลฯ) ให้ตอบว่า: "สวัสดีค่ะ น้อง I-SAVE Chatbot ค่ะพี่ๆ สามารถสอบถามข้อมูล หรือพิมพ์คำถามที่ต้องการได้เลยนะคะ น้องยินดีช่วยเหลือค่ะ"
9. ถ้า message ไม่เกี่ยวกับข้อมูลในระบบ I-SAVE เลย (ไม่ว่าจะเป็นคำถาม, ข้อความส่วนตัว, ความรู้สึก, เรื่องทั่วไป ฯลฯ) ให้ตอบว่าเท่านี้เท่านั้น: "ขออภัยค่ะ น้อง I-SAVE Chatbot ยังไม่สามารถตอบคำถามนี้ได้ในขณะนี้\nรบกวนพี่ๆ สอบถามเฉพาะข้อมูลที่เกี่ยวข้องกับระบบ I-SAVE หรือหัวข้อที่น้องรองรับนะคะ" — ห้ามตอบเพิ่มเติม ห้าม empathize หรือแสดงความเห็นใจ
10. คำว่า "วีค" หรือ "week" ในการตอบกลับภาษาไทย ให้ใช้ "สัปดาห์" เสมอ เช่น "สัปดาห์ที่ 22" ไม่ใช่ "week 22" หรือ "วีค 22"
11. เมื่อมีเครื่องว่างหลายกลุ่ม ให้ตอบเป็น summary ก่อน เช่น "มีเครื่องว่างรวม **XX เครื่อง** ใน YY กลุ่ม" แล้วถามว่า "ต้องการดูรายละเอียดแต่ละกลุ่มเพิ่มเติมไหมคะ"
12. ถ้าไม่ระบุ Item หรือกลุ่มเครื่อง ให้ตอบเป็นภาพรวมในรูปแบบนี้:
    "พบ Item ในแผนทั้งหมด [จำนวน] รายการ อยู่ใน [จำนวน] กลุ่มเครื่อง เช่น [รายชื่อกลุ่มหลัก]
    KP_Weight รวม [ยอดรวม] ตัน
    ต้องการดูรายละเอียดเพิ่มเติมไหมคะ เช่น Item, กลุ่มเครื่อง, Gauge หรือช่วงสัปดาห์"
13. ถ้ารหัส Item ที่ผู้ใช้ระบุเป็นตัวย่อและมีผลลัพธ์มากกว่า 1 รายการ ให้แสดงรายชื่อเต็มเป็นตัวเลือก 1, 2, 3, 4 ก่อน แล้วถามว่า "พี่ๆ ต้องการดู Item ไหนคะ" แทนที่จะแสดงผลทั้งหมดทันที
14. เมื่อผู้ใช้ถามเกี่ยวกับ item เฉพาะเจาะจง ให้ตอบในรูปแบบนี้:
    "Item [รหัส] สามารถทอได้ที่กลุ่มเครื่อง [กลุ่ม] โดยมีรายละเอียดแผนทอ ดังนี้
    1.สัปดาห์ที่ [YW] จำนวน [KP_Weight] ตัน
    2.สัปดาห์ที่ [YW] จำนวน [KP_Weight] ตัน
    ...
    หากต้องการสอบถามเรื่องไหนเพิ่มเติม สามารถพิมพ์สอบถามได้เลยค่ะ"
    - ใช้ unit เป็น "ตัน" เสมอ (แม้ข้อมูลในระบบจะเก็บเป็น kg ให้แสดงค่าเดิมแต่เปลี่ยน label เป็น ตัน)
    - ถ้า item อยู่หลายกลุ่มเครื่อง ให้แสดงแต่ละกลุ่มแยกกัน"""

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
                "YW=สัปดาห์, Group=กลุ่มเครื่อง, Guage=เกจ, "
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
            return header + '\n' + '\n'.join(result)
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
            if group and group.lower() not in group_col:
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

    async def process_message(
        self,
        user_message: str,
        username: str = 'คุณ',  # noqa: ARG002 — kept for API compatibility
        conversation_history: Optional[List[Dict]] = None,
    ) -> ProcessedResponse:
        history_msgs = self._build_history_messages(conversation_history or [])
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(min_yw=_min_plannable_yw())

        messages = [
            {"role": "system", "content": system_prompt},
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
                return ProcessedResponse(
                    message=f"ขออภัยครับ ระบบ AI ขัดข้องชั่วคราว ({e})",
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
                return ProcessedResponse(
                    message=_clean_response(msg.content or "ขออภัยครับ ไม่สามารถตอบได้"),
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
                    suggestions=self._get_suggestions(tool_calls_log),
                )

        return ProcessedResponse(
            message="ขออภัยครับ ระบบประมวลผลนานเกินไป กรุณาถามใหม่อีกครั้ง",
            response_type='text',
            processing_path='agent',
            mcp_calls=tool_calls_log,
            metadata={'intent': 'agent', 'confidence': 0.0, 'matched_keywords': []},
        )

    def _get_suggestions(self, tool_calls_log: list) -> list:
        tools_used = {c['tool'] for c in tool_calls_log}
        if 'get_item_plan' in tools_used or 'get_knit_plan' in tools_used:
            return ['ดูเครื่องว่างสำหรับ item นี้', 'ดู KP Weight ทั้งหมด', 'ดูแผนทอสัปดาห์นี้']
        if 'get_machine_capacity' in tools_used:
            return ['ดูเครื่องว่าง week ถัดไป', 'ดูการจอง', 'ดูแผนทอ']
        if 'get_booking' in tools_used:
            return ['ดูเครื่องว่าง', 'ดูแผนทอ', 'ดู item plan']
        return ['ข้อมูลเครื่องจักร', 'ข้อมูล Item', 'ข้อมูล Capacity']


_response_processor_instance = None


def get_response_processor() -> ResponseProcessor:
    global _response_processor_instance
    if _response_processor_instance is None:
        _response_processor_instance = ResponseProcessor()
    return _response_processor_instance
