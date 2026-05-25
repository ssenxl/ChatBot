#!/usr/bin/env python3
"""
Excel MCP Server - จัดการการทำงานกับ Excel files
"""

import asyncio
import json
import os
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Any
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)

# Excel operations
class ExcelManager:
    def __init__(self):
        self.excel_files = {}
        self.default_folder = "excel_exports"
        
        # สร้างโฟลเดอร์สำหรับเก็บไฟล์ Excel
        if not os.path.exists(self.default_folder):
            os.makedirs(self.default_folder)
    
    def create_excel_from_data(self, data: List[Dict], filename: str = None) -> str:
        """สร้างไฟล์ Excel จากข้อมูล"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.xlsx"
        
        filepath = os.path.join(self.default_folder, filename)
        
        # แปลงข้อมูลเป็น DataFrame
        df = pd.DataFrame(data)
        
        # บันทึกเป็น Excel
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Report', index=False)
            
            # ถ้ามีข้อมูลมาก ให้สร้าง summary sheet
            if len(df) > 0:
                summary_data = {
                    'Metric': ['Total Rows', 'Total Columns', 'Generated Time'],
                    'Value': [len(df), len(df.columns), datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        return filepath
    
    def read_excel_data(self, filepath: str) -> Dict:
        """อ่านข้อมูลจากไฟล์ Excel"""
        try:
            # อ่านทุก sheets
            excel_data = pd.read_excel(filepath, sheet_name=None)
            
            result = {}
            for sheet_name, df in excel_data.items():
                # แปลง DataFrame เป็น list of dicts
                result[sheet_name] = {
                    'data': df.to_dict('records'),
                    'columns': df.columns.tolist(),
                    'row_count': len(df),
                    'column_count': len(df.columns)
                }
            
            return {
                'success': True,
                'file_path': filepath,
                'sheets': result
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def append_to_excel(self, filepath: str, data: List[Dict], sheet_name: str = None) -> Dict:
        """เพิ่มข้อมูลลงในไฟล์ Excel ที่มีอยู่"""
        try:
            # อ่านไฟล์เดิม
            if os.path.exists(filepath):
                existing_data = pd.read_excel(filepath, sheet_name=sheet_name or 0)
                new_data = pd.DataFrame(data)
                
                # รวมข้อมูล
                combined_data = pd.concat([existing_data, new_data], ignore_index=True)
            else:
                combined_data = pd.DataFrame(data)
            
            # เขียนทับไฟล์เดิม
            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                combined_data.to_excel(writer, sheet_name=sheet_name or 'Sheet1', index=False)
            
            return {
                'success': True,
                'message': f'Added {len(data)} rows to {filepath}',
                'total_rows': len(combined_data)
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

# สร้าง Excel MCP Server
server = Server("excel-server")
excel_manager = ExcelManager()

@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    """แสดงรายการ Excel resources"""
    resources = []
    
    # ตรวจสอบไฟล์ Excel ในโฟลเดอร์
    if os.path.exists(excel_manager.default_folder):
        for filename in os.listdir(excel_manager.default_folder):
            if filename.endswith(('.xlsx', '.xls')):
                filepath = os.path.join(excel_manager.default_folder, filename)
                resources.append(
                    Resource(
                        uri=f"excel://{filepath}",
                        name=f"Excel File: {filename}",
                        description=f"Excel file in {excel_manager.default_folder}",
                        mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                )
    
    return resources

@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    """อ่านข้อมูลจาก Excel resource"""
    if uri.startswith("excel://"):
        filepath = uri.replace("excel://", "")
        result = excel_manager.read_excel_data(filepath)
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    raise ValueError(f"Unknown resource URI: {uri}")

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """แสดงรายการ Excel tools"""
    return [
        Tool(
            name="create_excel_report",
            description="สร้างไฟล์ Excel จากข้อมูล",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "array",
                        "description": "ข้อมูลที่จะสร้างเป็น Excel (list of dictionaries)",
                        "items": {"type": "object"}
                    },
                    "filename": {
                        "type": "string", 
                        "description": "ชื่อไฟล์ Excel (ไม่รวม .xlsx)",
                        "default": None
                    }
                },
                "required": ["data"]
            }
        ),
        Tool(
            name="read_excel_file",
            description="อ่านข้อมูลจากไฟล์ Excel",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "พาธของไฟล์ Excel"
                    }
                },
                "required": ["filepath"]
            }
        ),
        Tool(
            name="append_to_excel",
            description="เพิ่มข้อมูลลงในไฟล์ Excel ที่มีอยู่",
            inputSchema={
                "type": "object", 
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "พาธของไฟล์ Excel"
                    },
                    "data": {
                        "type": "array",
                        "description": "ข้อมูลที่จะเพิ่ม (list of dictionaries)",
                        "items": {"type": "object"}
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "ชื่อ sheet ที่จะเพิ่มข้อมูล",
                        "default": None
                    }
                },
                "required": ["filepath", "data"]
            }
        ),
        Tool(
            name="list_excel_files",
            description="แสดงรายการไฟล์ Excel ที่มีอยู่",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
    """จัดการการเรียกใช้ Excel tools"""
    
    if name == "create_excel_report":
        data = arguments.get("data", [])
        filename = arguments.get("filename")
        
        if not data:
            return [TextContent(type="text", text="Error: data is required")]
        
        try:
            filepath = excel_manager.create_excel_from_data(data, filename)
            return [TextContent(
                type="text", 
                text=f"Excel file created successfully: {filepath}"
            )]
        except Exception as e:
            return [TextContent(type="text", text=f"Error creating Excel: {str(e)}")]
    
    elif name == "read_excel_file":
        filepath = arguments.get("filepath")
        
        if not filepath:
            return [TextContent(type="text", text="Error: filepath is required")]
        
        result = excel_manager.read_excel_data(filepath)
        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]
    
    elif name == "append_to_excel":
        filepath = arguments.get("filepath")
        data = arguments.get("data", [])
        sheet_name = arguments.get("sheet_name")
        
        if not filepath or not data:
            return [TextContent(type="text", text="Error: filepath and data are required")]
        
        result = excel_manager.append_to_excel(filepath, data, sheet_name)
        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]
    
    elif name == "list_excel_files":
        files = []
        if os.path.exists(excel_manager.default_folder):
            for filename in os.listdir(excel_manager.default_folder):
                if filename.endswith(('.xlsx', '.xls')):
                    filepath = os.path.join(excel_manager.default_folder, filename)
                    file_info = {
                        'filename': filename,
                        'filepath': filepath,
                        'size': os.path.getsize(filepath),
                        'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
                    }
                    files.append(file_info)
        
        return [TextContent(
            type="text",
            text=json.dumps(files, ensure_ascii=False, indent=2)
        )]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def main():
    """Run the Excel MCP server"""
    # เพิ่ม pandas และ openpyxl ใน requirements
    try:
        import pandas as pd
        import openpyxl
    except ImportError:
        print("Error: Required packages not installed. Run:")
        print("pip install pandas openpyxl")
        return
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="excel-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities=None,
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
