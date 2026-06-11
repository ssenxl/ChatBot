"""Unit test สำหรับ _build_chart_spec — ทดสอบแปลง render_chart arguments เป็น Chart.js spec"""
import json
import sys

from response_processor import ResponseProcessor

# _build_chart_spec ไม่ใช้ self จึงเรียกแบบ unbound ได้ ไม่ต้อง init (เลี่ยง OpenAI client)
build = lambda raw: ResponseProcessor._build_chart_spec(None, raw)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


# 1. bar chart ปกติ (เคส capacity ต่อ week)
spec, msg = build(json.dumps({
    "chart_type": "bar",
    "title": "Capacity ว่างรายสัปดาห์",
    "labels": ["202624", "202625", "202626"],
    "datasets": [{"label": "Ava (kg)", "data": [1200, 850.5, 0]}],
    "y_label": "kg",
}))
check("bar chart spec created", spec is not None)
check("type=bar", spec["type"] == "bar", spec)
check("labels preserved", spec["labels"] == ["202624", "202625", "202626"])
check("data rounded/float", spec["datasets"][0]["data"] == [1200.0, 850.5, 0.0], spec["datasets"])
check("title/y_label preserved", spec["title"] == "Capacity ว่างรายสัปดาห์" and spec["y_label"] == "kg")

# 2. line chart หลาย dataset (แนวโน้มเครื่องหลายกลุ่ม)
spec, _ = build(json.dumps({
    "chart_type": "line",
    "labels": ["202624", "202625"],
    "datasets": [
        {"label": "SKP", "data": [10, 20]},
        {"label": "SKPLE", "data": [5, "7.25"]},  # string number ต้อง parse ได้
    ],
}))
check("line multi-dataset", spec is not None and len(spec["datasets"]) == 2)
check("string number parsed", spec["datasets"][1]["data"] == [5.0, 7.25], spec["datasets"])

# 3. chart_type ไม่รู้จัก → fallback เป็น bar
spec, _ = build(json.dumps({"chart_type": "radar", "labels": ["a"], "datasets": [{"label": "x", "data": [1]}]}))
check("unknown type falls back to bar", spec is not None and spec["type"] == "bar")

# 4. ค่า non-numeric ใน data → กลายเป็น 0 ไม่ crash
spec, _ = build(json.dumps({"chart_type": "pie", "labels": ["a", "b"], "datasets": [{"label": "x", "data": [3, None]}]}))
check("non-numeric coerced to 0", spec is not None and spec["datasets"][0]["data"] == [3.0, 0])

# 5. JSON พัง → คืน None พร้อม error message ภาษาไทย
spec, msg = build("{not json")
check("invalid json returns None", spec is None and "ไม่ถูกต้อง" in msg, msg)

# 6. ไม่มี labels → คืน None
spec, msg = build(json.dumps({"chart_type": "bar", "labels": [], "datasets": [{"label": "x", "data": [1]}]}))
check("empty labels rejected", spec is None, spec)

# 7. dataset ว่าง → คืน None
spec, msg = build(json.dumps({"chart_type": "bar", "labels": ["a"], "datasets": []}))
check("empty datasets rejected", spec is None, spec)

# 8. dataset ที่ data ว่างถูกตัดทิ้ง
spec, _ = build(json.dumps({
    "chart_type": "bar", "labels": ["a"],
    "datasets": [{"label": "empty", "data": []}, {"label": "ok", "data": [9]}],
}))
check("empty-data dataset dropped", spec is not None and len(spec["datasets"]) == 1 and spec["datasets"][0]["label"] == "ok")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
