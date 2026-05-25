#!/usr/bin/env python3
"""
ตัวอย่างการเชื่อมต่อ Intent Detection กับ Excel
"""

import asyncio
import json
from intent_detector import get_intent_detector
from mcp_client import get_mcp_client

async def demo_excel_integration():
    """ทดสอบการเชื่อมต่อ Excel กับ Intent Detection"""
    
    # Initialize components
    intent_detector = get_intent_detector()
    mcp_client = get_mcp_client()
    
    # Initialize MCP servers
    try:
        await mcp_client.initialize_servers()
        print("✅ MCP servers initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize MCP servers: {e}")
        return
    
    # Test messages with Excel intents
    test_messages = [
        "ช่วยสร้างไฟล์ excel สำหรับรายงานยอดขาย",
        "อยาก export ข้อมูลเป็น excel",
        "ดาวน์โหลดข้อมูลเป็นไฟล์ xlsx",
        "ส่งออกรายงานเป็น excel"
    ]
    
    print("\n=== Excel Intent Detection Test ===")
    
    for message in test_messages:
        print(f"\n📝 Message: {message}")
        
        # Detect intent
        intent_result = intent_detector.detect_intent(message)
        print(f"🎯 Intent: {intent_result.intent}")
        print(f"📊 Confidence: {intent_result.confidence:.2f}")
        print(f"🔧 Processing Path: {intent_result.processing_path}")
        print(f"🏷️  Matched Keywords: {intent_result.matched_keywords}")
        
        # If Excel intent detected, try to call Excel MCP tools
        if intent_result.intent in ['excel_report', 'export_excel'] and intent_result.mcp_server:
            try:
                # List available Excel tools
                tools = await mcp_client.get_tools('excel')
                print(f"🛠️  Available Excel tools: {[tool.name for tool in tools]}")
                
                # Example: Create sample Excel file
                if 'create_excel_report' in [tool.name for tool in tools]:
                    sample_data = [
                        {'Product': 'Product A', 'Sales': 1000, 'Date': '2024-01-01'},
                        {'Product': 'Product B', 'Sales': 1500, 'Date': '2024-01-02'},
                        {'Product': 'Product C', 'Sales': 800, 'Date': '2024-01-03'}
                    ]
                    
                    result = await mcp_client.call_tool(
                        'excel',
                        'create_excel_report',
                        {'data': sample_data, 'filename': f'sales_report_{message[:10]}'}
                    )
                    
                    if result.get('success'):
                        print(f"✅ Excel file created: {result.get('result', [{}])[0].get('text', 'N/A')}")
                    else:
                        print(f"❌ Failed to create Excel file")
                        
            except Exception as e:
                print(f"❌ Error calling Excel MCP: {e}")

async def demo_excel_data_flow():
    """ทดสอบ flow การทำงานกับ Excel ข้อมูลจริง"""
    
    print("\n=== Excel Data Flow Demo ===")
    
    mcp_client = get_mcp_client()
    
    try:
        # 1. สร้างข้อมูลตัวอย่าง
        sample_data = [
            {'รหัสสินค้า': 'ITEM001', 'ชื่อสินค้า': 'เส้นด้ายฝ้าย', 'จำนวน': 100, 'ราคา': 50.00},
            {'รหัสสินค้า': 'ITEM002', 'ชื่อสินค้า': 'เส้นด้ายไทย', 'จำนวน': 200, 'ราคา': 75.00},
            {'รหัสสินค้า': 'ITEM003', 'ชื่อสินค้า': 'เส้นด้ายผสม', 'จำนวน': 150, 'ราคา': 60.00}
        ]
        
        # 2. สร้างไฟล์ Excel
        print("📊 สร้างไฟล์ Excel...")
        result = await mcp_client.call_tool(
            'excel',
            'create_excel_report',
            {'data': sample_data, 'filename': 'product_inventory'}
        )
        
        if result.get('success'):
            excel_path = result.get('result', [{}])[0].get('text', '').replace('Excel file created successfully: ', '')
            print(f"✅ สร้างไฟล์สำเร็จ: {excel_path}")
            
            # 3. อ่านข้อมูลกลับจาก Excel
            print("\n📖 อ่านข้อมูลจาก Excel...")
            read_result = await mcp_client.call_tool(
                'excel',
                'read_excel_file',
                {'filepath': excel_path}
            )
            
            if read_result.get('success'):
                excel_data = json.loads(read_result.get('result', [{}])[0].get('text', '{}'))
                if excel_data.get('success'):
                    print(f"📋 พบ {len(excel_data.get('sheets', {}))} sheets")
                    for sheet_name, sheet_data in excel_data.get('sheets', {}).items():
                        print(f"  - Sheet '{sheet_name}': {sheet_data.get('row_count', 0)} rows")
            
            # 4. เพิ่มข้อมูลลงในไฟล์เดิม
            print("\n➕ เพิ่มข้อมูลใหม่...")
            new_data = [
                {'รหัสสินค้า': 'ITEM004', 'ชื่อสินค้า': 'เส้นด้ายพิเศษ', 'จำนวน': 80, 'ราคา': 90.00}
            ]
            
            append_result = await mcp_client.call_tool(
                'excel',
                'append_to_excel',
                {'filepath': excel_path, 'data': new_data}
            )
            
            if append_result.get('success'):
                append_info = json.loads(append_result.get('result', [{}])[0].get('text', '{}'))
                if append_info.get('success'):
                    print(f"✅ เพิ่มข้อมูลสำเร็จ: {append_info.get('message', '')}")
                    print(f"📊 จำนวนข้อมูลทั้งหมด: {append_info.get('total_rows', 0)} rows")
        
        # 5. แสดงรายการไฟล์ Excel ทั้งหมด
        print("\n📁 รายการไฟล์ Excel ทั้งหมด...")
        list_result = await mcp_client.call_tool('excel', 'list_excel_files', {})
        
        if list_result.get('success'):
            files = json.loads(list_result.get('result', [{}])[0].get('text', '[]'))
            print(f"พบ {len(files)} ไฟล์:")
            for file_info in files:
                print(f"  - {file_info.get('filename', '')} ({file_info.get('size', 0)} bytes)")
        
    except Exception as e:
        print(f"❌ Error in Excel data flow: {e}")

if __name__ == "__main__":
    print("🚀 Starting Excel Integration Demo")
    
    # Run demo
    asyncio.run(demo_excel_integration())
    asyncio.run(demo_excel_data_flow())
    
    print("\n✨ Demo completed!")
