"""
สาธิตพฤติกรรม token expiration
"""

import time
from datetime import datetime, timedelta
from auth import AzureTokenManager

def demo_token_behavior():
    """แสดงพฤติกรรม token"""
    
    print("=== สาธิต Token Expiration ===\n")
    
    # สมมติ token manager
    token_manager = AzureTokenManager("tenant123", "client456")
    
    # จำลองการเก็บ token (อายุ 1 ชั่วโมง)
    print("1. ขอ token เวลา 12:00")
    token_manager.cache_token("test_key", "abc123token", 3600)  # 1 ชั่วโมง
    
    # ทดสอบดึง token ในเวลาต่างๆ
    test_times = [
        (12, 50, "ใช้ได้ - อีก 10 นาทีหมด"),
        (12, 56, "ใช้ได้ - อีก 4 นาทีหมด"), 
        (12, 57, "❌ หมดอายุแล้ว (จะ refresh)"),
        (13, 5, "❌ หมดอายุแน่นอน")
    ]
    
    for hour, minute, description in test_times:
        # จำลองเวลา
        current_time = datetime.now().replace(hour=hour, minute=minute, second=0)
        
        # แก้ไข get_cached_token ชั่วคราวเพื่อทดสอบ
        if "test_key" in token_manager.token_cache:
            token_data = token_manager.token_cache["test_key"]
            expires_at = datetime.fromisoformat(token_data['expires_at'])
            
            # จำลองการเช็คอายุ
            time_remaining = expires_at - current_time
            is_valid = current_time < expires_at - timedelta(minutes=5)
            
            print(f"🕐 {hour:02d}:{minute:02d} - {description}")
            print(f"   เหลือเวลา: {time_remaining}")
            print(f"   สถานะ: {'✅ ใช้ได้' if is_valid else '❌ ต้อง refresh'}\n")

def real_world_scenarios():
    """สถานการณ์จริง"""
    
    print("=== สถานการณ์จริง ===\n")
    
    scenarios = [
        {
            "name": "ใช้งานปกติ (ทุก 15 นาที)",
            "pattern": "✅ Auto-refresh ทุกครั้ง",
            "user_experience": "ไม่รู้สึกว่า token หมด"
        },
        {
            "name": "ใช้งานนานๆ (ทุก 2 ชั่วโมง)",
            "pattern": "🔄 Refresh ทุกครั้งที่ใช้",
            "user_experience": "รอสักครู่ตอนเรียกครั้งแรก"
        },
        {
            "name": "ใช้ครั้งเดียวแล้วทิ้งไว้",
            "pattern": "⏰ Token หมดอายุเอง",
            "user_experience": "ครั้งต่อไปต้องขอใหม่"
        },
        {
            "name": "ปิด-เปิด app ภายใน 1 ชั่วโมง",
            "pattern": "📁 โหลดจาก cache",
            "user_experience": "เร็วกว่า ไม่ต้องขอใหม่"
        }
    ]
    
    for scenario in scenarios:
        print(f"📋 {scenario['name']}")
        print(f"   พฤติกรรม: {scenario['pattern']}")
        print(f"   ผลต่อผู้ใช้: {scenario['user_experience']}\n")

if __name__ == "__main__":
    demo_token_behavior()
    real_world_scenarios()
    
    print("=== สรุป ===")
    print("🔑 Token จะหมดอายุตามเวลาจริง (ไม่ใช่ตามการใช้งาน)")
    print("🤖 ระบบจะ refresh อัตโนมัติ 5 นาทีก่อนหมด")
    print("💾 Cache ช่วยให้ไม่ต้องขอใหม่ทุกครั้ง")
    print("⚡ ครั้งแรกอาจช้า ครั้งต่อๆ ไปเร็วขึ้น")
