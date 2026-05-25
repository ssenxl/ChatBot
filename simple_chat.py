#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Power BI Simple Chatbot - ไม่ต้องการติดตั้ง dependencies
ใช้งานได้เลยทันที
"""

import json
import sqlite3
from datetime import datetime
import hashlib

class SimpleChatbot:
    def __init__(self):
        self.db_file = 'simple_chat.db'
        self.init_database()
        self.conversations = {}
        self.current_conversation = None
        
    def init_database(self):
        """สร้างฐานข้อมูล SQLite ง่ายๆ"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        # สร้างตารางผู้ใช้
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                role TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # สร้างตารางการสนทนา
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # สร้างตารางข้อความ
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # สร้าง user พื้นฐาน
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            # สร้าง user admin
            cursor.execute('''
                INSERT INTO users (username, password, email, role) VALUES
                    (?, ?, ?, ?)
            ''', ('admin', self.hash_password('admin123'), 'admin@powerbi.com', 'admin'))
            
            # สร้าง user ธรรม
            cursor.execute('''
                INSERT INTO users (username, password, email, role) VALUES
                    (?, ?, ?, ?)
            ''', ('user', self.hash_password('user123'), 'user@powerbi.com', 'user'))
        
        conn.commit()
        conn.close()
        print("✅ ฐานข้อมูล SQLite พร้อมใช้งาน")
    
    def hash_password(self, password):
        """Hash รหัสผ่าน"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def verify_password(self, password, hashed):
        """ตรวจสอบรหัสผ่าน"""
        return self.hash_password(password) == hashed
    
    def authenticate_user(self, username, password):
        """ตรวจสอบผู้ใช้"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, email, role FROM users 
            WHERE username = ? AND password = ?
        ''', (username, self.hash_password(password)))
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'role': user[3]
            }
        return None
    
    def create_conversation(self, user_id, title=None):
        """สร้างการสนทนาใหม่"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO conversations (user_id, title)
            VALUES (?, ?)
        ''', (user_id, title or f"สนทนา {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
        
        conversation_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return conversation_id
    
    def get_user_conversations(self, user_id):
        """ดึงรายการการสนทนาของผู้ใช้"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC
        ''', (user_id,))
        
        conversations = []
        for row in cursor.fetchall():
            conversations.append({
                'id': row[0],
                'title': row[1],
                'created_at': row[2],
                'updated_at': row[3]
            })
        
        conn.close()
        return conversations
    
    def add_message(self, conversation_id, sender, message, message_type='text'):
        """เพิ่มข้อความในการสนทนา"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO messages (conversation_id, sender, message, message_type)
            VALUES (?, ?, ?, ?)
        ''', (conversation_id, sender, message, message_type))
        
        # อัปเดตเวลาของการสนทนา
        cursor.execute('''
            UPDATE conversations SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (conversation_id,))
        
        conn.commit()
        conn.close()
    
    def get_conversation_messages(self, conversation_id):
        """ดึงข้อความในการสนทนา"""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT sender, message, message_type, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        ''', (conversation_id,))
        
        messages = []
        for row in cursor.fetchall():
            messages.append({
                'sender': row[0],
                'message': row[1],
                'message_type': row[2],
                'created_at': row[3]
            })
        
        conn.close()
        return messages
    
    def generate_ai_response(self, message, user_id):
        """สร้างคำตอบจาก AI"""
        message_lower = message.lower()
        
        # ตรวจสอบคำหลัก
        if any(keyword in message_lower for keyword in ['สวัสดี', 'hello', 'สวัสดีครับ', 'สวัสดีครับ']):
            return {
                'message': f'สวัสดีครับ! ผมคือ Power BI Assistant ผู้ช่วยอัจฉริยะ\n\nวันนี้ต้องการให้ผมช่วยเหลืออะไรครับ?\n\n• เชื่อมต่อ Power BI API\n• ดูข้อมูล Workspaces\n• รันคำสั่ง DAX Query\n• วิเคราะห์ข้อมูล',
                'type': 'text'
            }
        
        elif any(keyword in message_lower for keyword in ['เชื่อมต่อ', 'connect', 'connection']):
            return {
                'message': 'เพื่อเชื่อมต่อกับ Power BI คุณต้องการ:\n\n1. ไปที่ Azure Portal\n2. สร้าง App Registration\n3. สร้าง Client Secret\n4. บันทึก Tenant ID, Client ID, Client Secret\n\n**หรือ** บอกข้อมูลให้ผม:\n- Tenant ID: xxxxx\n- Client ID: xxxxx\n- Client Secret: xxxxx\n\nผมจะช่วยเชื่อมต่อให้ครับ!',
                'type': 'text'
            }
        
        elif any(keyword in message_lower for keyword in ['workspace', 'workspaces', 'พื้นที่ทำงาน']):
            return {
                'message': 'ฟีเจอร์การดู Workspaces:\n\n1. ไปที่หน้า "การเชื่อมต่อ"\n2. กรอกข้อมูล Azure\n3. กด "เชื่อมต่อ"\n4. กลับมาที่หน้า "Workspaces"\n5. ดูรายการที่มี\n\n**ตัวอย่าง Workspace:**\n- Sales Dashboard\n- Marketing Reports\n- Finance Analytics\n\nต้องการดูรายละเอียด workspace ไหนครับ?',
                'type': 'text'
            }
        
        elif any(keyword in message_lower for keyword in ['dax', 'query', 'คำสั่ง']):
            return {
                'message': 'ฟีเจอร์การรัน DAX Query:\n\n**ตัวอย่างคำสั่ง:**\n```sql\nEVALUATE TOPN(10, Sales)\nSUMMARIZE(Sales, Product[Category])\nCALCULATE([Total Sales], DATE[Year] = 2024)\n```\n\n**วิธีใช้:**\n1. เชื่อมต่อ Power BI ก่อน\n2. เลือก Workspace และ Dataset\n3. กรอกคำสั่ง DAX\n4. กด "รัน Query"\n\nต้องการรันคำสั่งอะไรครับ?',
                'type': 'text'
            }
        
        elif any(keyword in message_lower for keyword in ['วิเคราะห์', 'analyze', 'analysis']):
            return {
                'message': 'ฟีเจอร์การวิเคราะห์ข้อมูล:\n\n**สิ่งที่สามารถทำ:**\n• สร้าง DAX Query สำหรับวิเคราะห์\n• สร้างรายงานและ Dashboard\n• หาข้อมูลเชิงลึกจากข้อมูลที่มี\n• ตรวจสอบคุณภาพข้อมูล\n• สร้าง KPI และ metrics\n\nต้องการวิเคราะห์ข้อมูลอะไรครับ?\n- มีข้อมูลอะไรบ้าง?\n- ต้องการตอบคำถามอะไร?\n- ต้องการสร้างรายงานแบบไหน?',
                'type': 'text'
            }
        
        else:
            return {
                'message': f'ฉันเข้าใจว่าคุณสนใจเกี่ยวกับ "{message}" ครับ\n\nลองใช้คำสั่งเหล่านี้:\n• "สวัสดี" - เริ่มต้นสนทนา\n• "เชื่อมต่อ Power BI" - ตั้งค่าการเชื่อมต่อ\n• "ดู Workspaces" - ดูรายการพื้นที่ทำงาน\n• "รัน DAX Query" - รันคำสั่ง DAX\n• "วิเคราะห์ข้อมูล" - วิเคราะห์ข้อมูล\n\nหรือถามคำสั่งที่คุณต้องการ บอกให้ฉันตรงๆ!',
                'type': 'text'
            }

def main():
    """ฟังก์ชันหลัก"""
    print("🤖 Power BI Simple Chatbot")
    print("=" * 50)
    
    # สร้าง chatbot instance
    chatbot = SimpleChatbot()
    
    # แสดงเมนูหลัก
    print("\n📋 เมนูหลัก:")
    print("1. เข้าสู่ระบบ")
    print("2. สร้างการสนทนาใหม่")
    print("3. ดูรายการสนทนา")
    print("4. ออกจากระบบ")
    print("0. ออกจากโปรแกรม")
    print("=" * 50)
    
    current_user = None
    
    while True:
        try:
            choice = input("\n🎯 เลือกเมนู (0-4): ").strip()
            
            if choice == '0':
                # ออกจากโปรแกรม
                print("👋 ออกจากระบบ สวัสดีครับ!")
                break
            
            elif choice == '1':
                # เข้าสู่ระบบ
                username = input("👤 ชื่อผู้ใช้: ").strip()
                password = input("🔒 รหัสผ่าน: ").strip()
                
                user = chatbot.authenticate_user(username, password)
                if user:
                    current_user = user
                    print(f"✅ เข้าสู่ระบบสำเร็จ! ยินดีต้อนรับคุณ {user['username']}")
                    print(f"📧 บทบ: {user['role']}")
                    print(f"📧 อีเมล: {user['email']}")
                else:
                    print("❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
            
            elif choice == '2':
                # สร้างการสนทนาใหม่
                if not current_user:
                    print("❌ กรุณาเข้าสู่ระบบก่อน")
                    continue
                
                title = input("📝 ตั้งชื่อการสนทนา: ").strip() or f"สนทนา {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                conversation_id = chatbot.create_conversation(current_user['id'], title)
                chatbot.current_conversation = conversation_id
                print(f"✅ สร้างการสนทนา: {title} (ID: {conversation_id})")
            
            elif choice == '3':
                # ดูรายการสนทนา
                if not current_user:
                    print("❌ กรุณาเข้าสู่ระบบก่อน")
                    continue
                
                conversations = chatbot.get_user_conversations(current_user['id'])
                if not conversations:
                    print("📭 ยังไม่มีการสนทนา")
                else:
                    print(f"\n📋 รายการสนทนา ({len(conversations)} รายการ):")
                    for i, conv in enumerate(conversations, 1):
                        print(f"  {i}. {conv['title']} - {conv['created_at']}")
            
            elif choice == '4':
                # แชทกับ AI
                if not current_user:
                    print("❌ กรุณาเข้าสู่ระบบก่อน")
                    continue
                
                if not chatbot.current_conversation:
                    print("❌ กรุณาสร้างการสนทนาก่อน")
                    continue
                
                print(f"\n💬 แชทกับ AI (การสนทนา ID: {chatbot.current_conversation})")
                print("พิมพ์ 'exit' เพื่อกลับไปเมนูหลัก")
                print("-" * 50)
                
                while True:
                    message = input("\n👤 คุณ: ").strip()
                    
                    if message.lower() == 'exit':
                        print("🔙 กลับไปเมนูหลัก")
                        break
                    
                    # บันทึกข้อความผู้ใช้
                    chatbot.add_message(chatbot.current_conversation, 'user', message)
                    print(f"👤 คุณ: {message}")
                    
                    # สร้างคำตอบ AI
                    ai_response = chatbot.generate_ai_response(message, current_user['id'])
                    
                    # บันทึกข้อความ AI
                    chatbot.add_message(chatbot.current_conversation, 'assistant', ai_response['message'], ai_response['type'])
                    
                    print(f"🤖 AI: {ai_response['message']}")
            
            else:
                print("❌ เลือกเมนูไม่ถูกต้อง กรุณาเลือก 0-4")
        
        except KeyboardInterrupt:
            print("\n👋 ออกจากโปรแกรม ตามความประสงทผู้ใช้")
            break
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    main()
