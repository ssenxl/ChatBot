# Azure Token Auto-Detection สำหรับ Power BI API

## ภาพรวม

ระบบสนับสนุนการขอ Azure token อัตโนมัติหลายวิธี:

1. **Managed Identity** (แนะนำสำหรับ Production บน Azure)
2. **Client Secret** (จาก Environment Variables)
3. **Interactive Flow** (สำหรับ Development)
4. **Device Code Flow** (สำหรับ Headless Environment)

## การติดตั้ง

```bash
pip install -r requirements.txt
```

## การตั้งค่า

### 1. สร้างไฟล์ `.env`

```bash
cp .env.example .env
```

แก้ไขไฟล์ `.env` ด้วยข้อมูลจริง:

```env
# สำหรับ Client Secret
AZURE_TENANT_ID=your-tenant-id-here
AZURE_CLIENT_ID=your-client-id-here
AZURE_CLIENT_SECRET=your-client-secret-here
```

### 2. การใช้งาน

#### แบบ Auto-detect (แนะนำ)

```python
from powerbi_api_connector import create_auto_connector

# สร้าง connector อัตโนมัติ
connector = create_auto_connector()
workspaces = connector.get_workspaces()
```

#### แบบ Manual

```python
from powerbi_api_connector import PowerBIAPIConnector

# ระบุ credentials เอง
connector = PowerBIAPIConnector(
    tenant_id="your-tenant-id",
    client_id="your-client-id", 
    client_secret="your-client-secret",
    auto_detect=False
)
workspaces = connector.get_workspaces()
```

## ลำดับการตรวจสอบ Auto-detect

ระบบจะตรวจสอบตามลำดับนี้:

1. **Managed Identity** - ถ้าพบ `AZURE_CLIENT_ID` หรือ `IDENTITY_ENDPOINT`
2. **Client Secret** - ถ้ามี `client_secret` ใน constructor
3. **Interactive Flow** - สำหรับการพัฒนาในเครื่อง
4. **Device Code Flow** - ถ้าวิธีอื่นไม่ได้

## การใช้กับ Flask API

### เชื่อมต่อแบบอัตโนมัติ

```javascript
// ส่ง POST ไปที่ /connect-auto
fetch('/connect-auto', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'}
})
.then(response => response.json())
.then(data => console.log(data));
```

### เชื่อมต่อแบบ Manual + Auto-detect

```javascript
// ส่ง POST ไปที่ /connect
fetch('/connect', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        auto_detect: true  // หรือ false พร้อมข้อมูล credentials
    })
})
.then(response => response.json())
.then(data => console.log(data));
```

## Token Cache

ระบบจะเก็บ token ไว้ใน cache (`token_cache.json`) และ refresh อัตโนมัติก่อนหมดอายุ 5 นาที

## สถานการณ์การใช้งาน

### Production บน Azure

ใช้ **Managed Identity**:

```bash
# บน Azure VM/App Service ไม่ต้องตั้งค่าอะไร
# ระบบจะใช้ Managed Identity อัตโนมัติ
```

### Development บนเครื่อง

ใช้ **Client Secret** หรือ **Interactive**:

```bash
# ตั้งค่าใน .env
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
```

### CI/CD Pipeline

ใช้ **Service Principal** หรือ **Managed Identity**:

```yaml
# GitHub Actions example
env:
  AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
  AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
  AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
```

## การตรวจสอบสถานะ

```python
# ตรวจสอบว่าเชื่อมต่อสำเร็จหรือไม่
try:
    workspaces = connector.get_workspaces()
    print(f"เชื่อมต่อสำเร็จ! พบ {len(workspaces)} workspaces")
except Exception as e:
    print(f"เชื่อมต่อล้มเหลว: {e}")
```

## ข้อควรระวัง

- เก็บ `client_secret` ให้ปลอดภัย อย่าใส่ใน source code
- ใช้ Managed Identity ใน Production เมื่อเป็นไปได้
- Token จะหมดอายุประมาณ 1 ชั่วโมง ระบบจะ refresh อัตโนมัติ
- Cache file มีข้อมูล token ควรตั้งค่า permission ให้ปลอดภัย
