"""ตั้งค่า env ที่จำเป็นก่อน import โมดูลแอป (เช่น OpenAI client ต้องมี API key)."""
import os
import sys
from pathlib import Path

# ให้ import โมดูลที่ root ของโปรเจกต์ได้ (response_processor, data_cache, rate_limit)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
