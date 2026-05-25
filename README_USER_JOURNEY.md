# User Journey Chatbot System with MCP Integration

ระบบ Chatbot ที่ใช้ Intent Detection, MCP (Model Context Protocol), และ Smart Suggestions

## 🎯 Features

### 1. **Intent Detection System**
- ตรวจจับความตั้งใจของผู้ใช้อัตโนมัติ
- Confidence scoring (0.0 - 1.0)
- รองรับ intents:
  - `machine_capacity` - ข้อมูลเครื่องจักร
  - `item_data` - ข้อมูล Items/สินค้า
  - `knitting_plan` - แผนการทอ
  - `powerbi_report` - รายงาน Power BI
  - `data_analysis` - การวิเคราะห์ข้อมูล

### 2. **Three Processing Paths**

#### 🎯 Intent Mode (High Confidence >= 0.75)
- ใช้ intent-based response โดยตรง
- เรียก MCP tools ทันที
- Response รวดเร็วและแม่นยำ

#### 🔀 Hybrid Mode (Medium Confidence 0.50-0.75)
- ผสมผสาน intent detection + LLM
- เรียก MCP tools ตาม intent
- LLM สร้างคำตอบจากข้อมูล

#### 🤖 LLM Mode (Low Confidence < 0.50)
- ให้ LLM ประมวลผลเต็มรูปแบบ
- ใช้เมื่อไม่แน่ใจความตั้งใจของผู้ใช้

### 3. **MCP Integration**

#### MCP Servers
- **Power BI Server**: เข้าถึงข้อมูล workspaces, reports
- **Database Server**: Query ข้อมูลเครื่องจักร, items, แผนทอ
- **Tools Server**: เครื่องมือวิเคราะห์ข้อมูล

#### Available MCP Tools
```
powerbi/get_workspaces       - ดึงรายการ workspaces
powerbi/get_reports          - ดึงรายงานจาก workspace
database/query_machine_capacity - ข้อมูลกำลังการผลิต
database/query_items         - ข้อมูล items
database/query_knitting_plan - ข้อมูลแผนทอ
tools/analyze_data           - วิเคราะห์ข้อมูล
```

### 4. **Smart Suggestions**
- สร้าง suggestions ตาม context
- ปรับตามประวัติการสนทนา
- ติดตาม click rate สำหรับปรับปรุง

### 5. **Comprehensive Logging**
- Intent detection logs
- MCP interaction logs
- Suggestion analytics
- Processing path statistics

## 📁 โครงสร้างไฟล์

```
powerbi_api/
├── mcp_config.json              # MCP server configuration
├── mcp_client.py                # MCP client implementation
├── intent_detector.py           # Intent detection module
├── response_processor.py        # 3 processing paths
├── suggestion_engine.py         # Smart suggestions
├── database.py                  # Database with new tables
├── chatbot_app.py              # Flask app with new endpoints
└── mcp_servers/                # MCP server implementations
    ├── powerbi_mcp_server.py
    ├── database_mcp_server.py
    └── tools_mcp_server.py
```

## 🗄️ Database Schema

### ตารางใหม่

#### `intent_logs`
```sql
- id, conversation_id, message_id
- user_message, detected_intent
- confidence, matched_keywords
- processing_path, created_at
```

#### `mcp_interactions`
```sql
- id, conversation_id, message_id, intent_log_id
- mcp_server, tool_name
- tool_arguments, tool_result
- success, error_message, execution_time_ms
```

#### `suggestions`
```sql
- id, conversation_id, message_id
- suggestion_text, suggestion_intent
- priority, was_clicked, clicked_at
```

## 🚀 การใช้งาน

### 1. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 2. รันระบบ
```bash
python main.py
```

### 3. เข้าใช้งาน
เปิดเบราว์เซอร์ที่ `http://localhost:5000`

## 📡 API Endpoints ใหม่

### Intent & MCP
- `GET /api/intents` - ดึงรายการ intents
- `GET /api/mcp/tools` - ดึงรายการ MCP tools
- `GET /api/quick-actions` - ดึง quick actions

### Analytics
- `GET /conversations/<id>/analytics` - ดู analytics ของการสนทนา
- `POST /api/suggestions/<id>/click` - บันทึกการคลิก suggestion

## 🎨 User Journey Flow

```
START
  ↓
GREETING + LIST MENU
  ↓
USER INPUT
  ↓
INTENT DETECTION
  ↓
┌─────────────────┼─────────────────┐
↓                 ↓                 ↓
Low Conf      Medium Conf       High Conf
(< 0.50)      (0.50-0.75)      (>= 0.75)
  ↓                 ↓                 ↓
LLM Mode      Hybrid Mode       Intent Mode
  ↓                 ↓                 ↓
└─────────────────┼─────────────────┘
  ↓
MCP TOOL SELECTION (if applicable)
  ↓
EXECUTE via MCP SERVER
  ↓
RESPONSE + LOGGING
  ↓
SMART SUGGESTIONS
  ↓
DISPLAY TO USER
```

## 📊 ตัวอย่างการใช้งาน

### Example 1: High Confidence Intent
```
User: "ข้อมูลเครื่องจักร"
→ Intent: machine_capacity (confidence: 0.95)
→ Path: Intent Mode
→ MCP: database/query_machine_capacity
→ Response: ข้อมูลเครื่องจักรพร้อมสถานะ
→ Suggestions: ["ดูเครื่องจักรทั้งหมด", "ตรวจสอบสถานะ", ...]
```

### Example 2: Medium Confidence
```
User: "วิเคราะห์ข้อมูลลูกค้า"
→ Intent: data_analysis (confidence: 0.65)
→ Path: Hybrid Mode
→ MCP: tools/analyze_data + LLM interpretation
→ Response: การวิเคราะห์พร้อมคำอธิบาย
```

### Example 3: Low Confidence
```
User: "อยากทำอะไรดี"
→ Intent: unknown (confidence: 0.30)
→ Path: LLM Mode
→ Response: คำแนะนำพร้อมเมนู
→ Suggestions: ดึงจาก MCP capabilities
```

## 🔧 Configuration

### MCP Config (`mcp_config.json`)
```json
{
  "mcpServers": {
    "powerbi": { ... },
    "database": { ... },
    "tools": { ... }
  },
  "intents": {
    "machine_capacity": {
      "keywords": ["เครื่องจักร", "machine", "capacity"],
      "mcp_server": "database",
      "confidence_threshold": 0.8
    }
  }
}
```

## 📈 Analytics & Monitoring

### Conversation Analytics
```javascript
GET /conversations/{id}/analytics

Response:
{
  "total_messages": 15,
  "avg_confidence": 0.78,
  "processing_paths": {
    "intent": 8,
    "hybrid": 5,
    "llm": 2
  },
  "intent_distribution": {
    "machine_capacity": 5,
    "item_data": 3,
    ...
  },
  "mcp_calls": 10,
  "suggestion_analytics": [...]
}
```

## 🎯 Quick Actions

ระบบมี Quick Actions ที่แสดงเป็นปุ่มด่วน:
- 🏭 ข้อมูลเครื่องจักร (Machine Capacity)
- 📦 ข้อมูล Item
- 📊 ข้อมูล Capacity
- 📋 ข้อมูลแผนทอ (Knitting Plan)

## 🔐 Security

- Session-based authentication
- Role-based access control (user/admin)
- SQL injection protection
- Password hashing with werkzeug

## 🐛 Troubleshooting

### MCP Servers ไม่เริ่มต้น
- ตรวจสอบ `mcp_config.json`
- ดู logs ใน console
- ระบบจะใช้ fallback mode ถ้า MCP ล้มเหลว

### Intent Detection ไม่แม่นยำ
- เพิ่ม keywords ใน `mcp_config.json`
- ปรับ confidence thresholds
- ตรวจสอบ analytics เพื่อปรับปรุง

## 📝 License

MIT License

## 👥 Contributors

- Development Team
- I-SAVE Project

---

**Version**: 1.0.0  
**Last Updated**: March 24, 2026
