# Chatbot Web App

เว็บแอปแชทสำหรับองค์กร รองรับการสนทนากับ LLM พร้อม MCP Tools สำหรับดึงข้อมูลการผลิต, Power BI และ Excel โดยตรงจาก chat

## LLM

- **Model:** OpenAI GPT (default: `gpt-4o-mini`, กำหนดได้ผ่าน `OPENAI_MODEL`)
- **Streaming:** รองรับ streaming response แบบ real-time
- **Token tracking:** บันทึก prompt/completion tokens ทุก message

## MCP Tools

ระบบใช้ MCP (Model Context Protocol) ให้ LLM เรียกใช้ข้อมูลจริงจาก server ได้โดยตรง

### Database Tools
| Tool | คำอธิบาย |
|---|---|
| `query_machine_capacity` | ดึงข้อมูลกำลังการผลิตและความพร้อมของเครื่องจักร |
| `query_items` | ดึงข้อมูล item / รหัสสินค้า / KP Weight |
| `query_knitting_plan` | ดึงข้อมูลแผนการทอ (knitting plan) |

### Power BI Tools
| Tool | คำอธิบาย |
|---|---|
| `get_reports` | ดึงรายการรายงาน Power BI |

### Excel Tools
| Tool | คำอธิบาย |
|---|---|
| `create_excel_report` | สร้างไฟล์ Excel จากข้อมูลที่ query ได้ |
| `read_excel_file` | อ่านข้อมูลจากไฟล์ Excel |
| `append_to_excel` | เพิ่มข้อมูลต่อท้ายในไฟล์ Excel |
| `list_excel_files` | แสดงรายการไฟล์ Excel ที่มี |

## ฟีเจอร์หลัก

- **Chat:** สนทนากับ LLM พร้อม streaming, แยก conversation ตาม user
- **MCP Integration:** LLM เรียก tool ดึงข้อมูล production/BI/Excel อัตโนมัติ
- **Microsoft Teams:** รองรับ Bot Framework เชื่อมต่อ Teams โดยตรง
- **Morning Greeting:** ส่งสรุปข้อมูลการผลิตทุกเช้าให้ user อัตโนมัติ
- **Proactive Monitor:** แจ้งเตือน capacity alert เมื่อข้อมูลผิดปกติ
- **Admin Panel:** จัดการ user, role, token usage, support tickets
- **Rate Limit:** จำกัด 5 message/นาที ต่อ user
- **Avatar:** อัปโหลดรูปโปรไฟล์ได้

## การติดตั้ง

```bash
pip install -r requirements.txt
```

## Environment Variables

```bash
# LLM
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini          # optional, default: gpt-4o-mini

# Database
DATABASE_URL=postgresql://user:pass@host:5432/webchat

# Microsoft Teams (optional)
MicrosoftAppId=...
MicrosoftAppPassword=...

# Azure AD / Power BI (optional)
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...

# Signup whitelist (optional)
ALLOWED_SIGNUP_EMAILS=admin@company.com,user@company.com
SIGNUP_EMAIL_SOURCE_FILE=User_login/Sales Email Update.xlsx
SIGNUP_EMAIL_COLUMN=EMPLOYEE_EMAIL
```

## การรัน

```bash
# Local
python main.py

# Docker
docker compose up -d

# Deploy to server
.\deploy_to_webchat.ps1
```

เปิด `http://localhost:5000`

## Azure AD / Power BI Setup

1. **Azure Portal** > App registrations > New registration
2. บันทึก **Application (client) ID** และ **Directory (tenant) ID**
3. Certificates & secrets > New client secret > คัดลอก Value
4. API permissions > Add Power BI Service > เลือก `Dataset.Read.All`, `Report.Read.All`, `Workspace.Read.All` > Grant admin consent
