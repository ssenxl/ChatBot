# Chatbot Web App

เว็บแอปแชทที่รองรับการล็อกอินผู้ใช้ การสร้างหัวข้อสนทนาใหม่ และการกลับมาเปิดดูบทสนทนาเดิมของผู้ใช้คนเดิมได้

## การติดตั้ง

```bash
pip install -r requirements.txt
```

## การตั้งค่า

### จำกัดอีเมลที่สมัครสมาชิกได้ (Optional)

โดยค่าเริ่มต้นระบบจะดึงอีเมลที่อนุญาตจากไฟล์
`User_login/Sales Email Update.xlsx` คอลัมน์ `EMPLOYEE_EMAIL`

หากต้องการให้สมัครสมาชิกได้เฉพาะบางอีเมล ให้ตั้งค่า environment variable `ALLOWED_SIGNUP_EMAILS`
โดยคั่นอีเมลด้วยเครื่องหมายจุลภาค:

```bash
ALLOWED_SIGNUP_EMAILS=admin@company.com,owner@company.com
```

สามารถเปลี่ยนไฟล์หรือชื่อคอลัมน์ได้ด้วย:

```bash
SIGNUP_EMAIL_SOURCE_FILE=User_login/Sales Email Update.xlsx
SIGNUP_EMAIL_COLUMN=EMPLOYEE_EMAIL
```

ถ้าไม่ตั้งค่านี้ ระบบจะใช้รายการจากไฟล์ Excel เป็นหลัก
และจะเปิดให้สมัครได้ทุกอีเมลเฉพาะกรณีที่หาไฟล์ไม่เจอและไม่ได้กำหนด `ALLOWED_SIGNUP_EMAILS`

### 1. ลงทะเบียน Application ใน Azure AD

1. เข้าไปที่ [Azure Portal](https://portal.azure.com)
2. ไปที่ **Azure Active Directory** > **App registrations**
3. คลิก **New registration**
4. ตั้งชื่อ application และเลือก **Accounts in this organizational directory only**
5. บันทึก **Application (client) ID** และ **Directory (tenant) ID**

### 2. สร้าง Client Secret

1. ในหน้า app registration ไปที่ **Certificates & secrets**
2. คลิก **New client secret**
3. ตั้งชื่อและเลือกระยะเวลา
4. คัดลอกค่า **Value** ของ secret (จะแสดงครั้งเดียวเท่านั้น)

### 3. กำหนดสิทธิ์ Power BI

1. ในหน้า app registration ไปที่ **API permissions**
2. คลิก **Add a permission** > **Power BI Service**
3. เลือก **Application permissions**
4. ติ๊ก **Dataset.Read.All**, **Report.Read.All**, **Workspace.Read.All**
5. คลิก **Grant admin consent**

## การใช้งาน

รันเว็บแอป:

```bash
python chatbot_app.py
```

หรือใช้ entrypoint หลัก:

```bash
python main.py
```

จากนั้นเปิด `http://localhost:5000`

## ฟังก์ชันหลัก

- ล็อกอินและสมัครสมาชิกผู้ใช้
- สร้างหัวข้อสนทนาใหม่เมื่อต้องการเปลี่ยนเรื่อง
- เก็บบทสนทนาแยกตามผู้ใช้
- เปิดหัวข้อเดิมกลับมาดูต่อได้ภายหลัง
- เปลี่ยนชื่อหัวข้อและลบหัวข้อสนทนาได้

## ตัวอย่างการใช้งานเพิ่มเติม

```python
# สร้าง connector
pbi = PowerBIAPIConnector(tenant_id, client_id, client_secret)

# ดึงข้อมูลทั้งหมด
workspaces = pbi.get_workspaces()

# รัน DAX query
dax = "EVALUATE TOPN(100, Sales)"
result = pbi.execute_dax_query(workspace_id, dataset_id, dax)

# รีเฟรชข้อมูล
pbi.refresh_dataset(workspace_id, dataset_id)
```
