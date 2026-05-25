# Excel Integration สำหรับ Intent Detection

## ภาพรวม

ระบบรองรับการเชื่อมต่อ Intent Detection กับ Excel file operations ผ่าน MCP (Model Context Protocol) Server

## การติดตั้ง

### 1. Install Dependencies

```bash
pip install pandas openpyxl
```

### 2. Configuration

ไฟล์ `mcp_config.json` มีการตั้งค่า Excel MCP server และ intents:

```json
{
  "mcpServers": {
    "excel": {
      "command": "python",
      "args": ["mcp_servers/excel_mcp_server.py"],
      "description": "Excel file operations server",
      "enabled": true,
      "capabilities": {
        "resources": true,
        "tools": true,
        "prompts": false
      }
    }
  },
  "intents": {
    "excel_report": {
      "keywords": ["excel", "xlsx", "ไฟล์ excel", "ข้อมูล excel", "ออกรายงาน excel"],
      "mcp_server": "excel",
      "confidence_threshold": 0.8
    },
    "export_excel": {
      "keywords": ["ส่งออก", "export", "ดาวน์โหลด excel", "บันทึก excel"],
      "mcp_server": "excel", 
      "confidence_threshold": 0.7
    }
  }
}
```

## Excel Intents

### 1. excel_report
- **Keywords**: excel, xlsx, ไฟล์ excel, ข้อมูล excel, ออกรายงาน excel
- **MCP Server**: excel
- **Confidence Threshold**: 0.8
- **Use Cases**: สร้างรายงาน Excel, อ่านข้อมูล Excel

### 2. export_excel
- **Keywords**: ส่งออก, export, ดาวน์โหลด excel, บันทึก excel
- **MCP Server**: excel
- **Confidence Threshold**: 0.7
- **Use Cases**: ส่งออกข้อมูลเป็น Excel, บันทึกข้อมูล

## Excel MCP Tools

### 1. create_excel_report
สร้างไฟล์ Excel จากข้อมูล

```python
result = await mcp_client.call_tool(
    'excel',
    'create_excel_report',
    {
        'data': [
            {'Column1': 'Value1', 'Column2': 'Value2'},
            {'Column1': 'Value3', 'Column2': 'Value4'}
        ],
        'filename': 'report_name'  # optional
    }
)
```

### 2. read_excel_file
อ่านข้อมูลจากไฟล์ Excel

```python
result = await mcp_client.call_tool(
    'excel',
    'read_excel_file',
    {'filepath': 'path/to/excel_file.xlsx'}
)
```

### 3. append_to_excel
เพิ่มข้อมูลลงในไฟล์ Excel ที่มีอยู่

```python
result = await mcp_client.call_tool(
    'excel',
    'append_to_excel',
    {
        'filepath': 'path/to/excel_file.xlsx',
        'data': [{'Column1': 'NewValue1', 'Column2': 'NewValue2'}],
        'sheet_name': 'Sheet1'  # optional
    }
)
```

### 4. list_excel_files
แสดงรายการไฟล์ Excel ทั้งหมด

```python
result = await mcp_client.call_tool('excel', 'list_excel_files', {})
```

## ตัวอย่างการใช้งาน

### 1. Intent Detection + Excel

```python
from intent_detector import get_intent_detector
from mcp_client import get_mcp_client

# Detect intent
intent_detector = get_intent_detector()
message = "ช่วยสร้างไฟล์ excel สำหรับรายงานยอดขาย"
intent_result = intent_detector.detect_intent(message)

# If Excel intent detected
if intent_result.intent == 'excel_report':
    # Call Excel MCP tool
    mcp_client = get_mcp_client()
    await mcp_client.initialize_servers()
    
    result = await mcp_client.call_tool(
        'excel',
        'create_excel_report',
        {'data': sales_data, 'filename': 'sales_report'}
    )
```

### 2. Chatbot Integration

ใน `chatbot_app.py` ระบบจะ detect intent และเรียกใช้ Excel tools อัตโนมัติ:

```python
# Message: "อยาก export ข้อมูลเป็น excel"
# Intent: export_excel (confidence: 0.85)
# Processing: Call excel MCP server
```

## File Structure

```
powerbi_api/
├── mcp_servers/
│   └── excel_mcp_server.py      # Excel MCP Server
├── mcp_config.json              # Configuration
├── intent_detector.py           # Intent Detection
├── excel_integration_demo.py    # Demo Script
└── excel_exports/               # Generated Excel files
```

## Error Handling

ระบบจะ fallback ไปใช้ LLM mode ถ้า:
- Excel MCP server ไม่พร้อมใช้งาน
- Intent confidence < 0.5
- เกิดข้อผิดพลาดในการเรียก Excel tools

## Performance Considerations

- Excel files เก็บใน `excel_exports/` folder
- Auto-cleanup สำหรับไฟล์เก่า (> 7 days)
- Support large datasets ผ่าน pandas chunking
- Memory optimization สำหรับไฟล์ขนาดใหญ่

## Security

- Excel files จำกัดขนาดสูงสุด 50MB
- Validate input data ก่อนสร้าง Excel
- Sanitize filenames เพื่อป้องกัน path traversal
- Rate limiting สำหรับ Excel operations

## Testing

รัน demo script เพื่อทดสอบ:

```bash
python excel_integration_demo.py
```

## Troubleshooting

### Common Issues

1. **ModuleNotFoundError: No module named 'pandas'**
   ```bash
   pip install pandas openpyxl
   ```

2. **Excel MCP server not responding**
   - ตรวจสอบ `mcp_config.json` configuration
   - ตรวจสอบว่า `excel_mcp_server.py` อยู่ใน path ที่ถูกต้อง

3. **Permission denied creating Excel files**
   - ตรวจสอบสิทธิ์การเขียนใน `excel_exports/` folder
   - สร้าง folder ถ้ายังไม่มี: `mkdir excel_exports`

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Future Enhancements

- Support Excel templates
- Chart generation
- Formula support
- Multi-sheet operations
- Cloud Excel integration (OneDrive, SharePoint)
