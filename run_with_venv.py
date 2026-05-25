#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Power BI Chatbot Runner - ใช้ Virtual Environment อย่างถูกต้อง
"""

import os
import sys
import subprocess
from pathlib import Path

def find_venv_python():
    """หา Python executable ใน .venv"""
    current_dir = Path.cwd()
    venv_python = None
    
    # หา .venv folder
    venv_paths = [
        current_dir / ".venv" / "Scripts" / "python.exe",
        current_dir / ".venv" / "bin" / "python",
        current_dir / "venv" / "Scripts" / "python.exe",
        current_dir / "venv" / "bin" / "python",
    ]
    
    for path in venv_paths:
        if path.exists():
            venv_python = str(path)
            break
    
    return venv_python

def run_with_venv():
    """รัน chatbot ด้วย Python ใน venv"""
    print("🤖 Power BI Chatbot - Virtual Environment Runner")
    print("=" * 60)
    
    # หา Python ใน venv
    venv_python = find_venv_python()
    
    if venv_python:
        print(f"✅ พบ Virtual Environment Python: {venv_python}")
        print(f"📁 Current Directory: {Path.cwd()}")
    else:
        print("❌ ไม่พบ Virtual Environment")
        print("💡 สร้าง venv: python -m venv .venv")
        print("💡 เปิด venv: .venv\\Scripts\\activate")
        return
    
    # ตรวจสอบ dependencies
    print("\n📦 ตรวจสอบ dependencies...")
    try:
        result = subprocess.run([
            venv_python, "-c", 
            "import flask, werkzeug, azure.identity, msal, requests; print('✅ Dependencies พร้อม')"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(result.stdout.strip())
        else:
            print("❌ Dependencies ไม่พร้อม")
            print("📦 กำลังติดตั้ง...")
            
            install_result = subprocess.run([
                venv_python, "-m", "pip", "install", 
                "flask", "werkzeug", "azure-identity", "msal", "requests"
            ], capture_output=True, text=True)
            
            if install_result.returncode == 0:
                print("✅ ติดตั้ง dependencies สำเร็จ")
            else:
                print(f"❌ ติดตั้งล้มเหลว: {install_result.stderr}")
                return
    except subprocess.TimeoutExpired:
        print("⏰ ตรวจสอบ timeout ใช้ Python หลักแทน")
        venv_python = sys.executable
    
    # รัน chatbot
    print("\n🚀 กำลังเริ่มต้น Power BI Chatbot...")
    print("=" * 60)
    print(f"🐍 Python: {venv_python}")
    print("📁 App: chatbot_app.py")
    print("🌐 URL: http://localhost:5000")
    print("🔧 Debug Mode: ON")
    print("🎯 กด Ctrl+C เพื่อหยุด")
    print("=" * 60)
    
    try:
        # เพิ่ม current directory ใน Python path
        env = os.environ.copy()
        if 'PYTHONPATH' in env:
            env['PYTHONPATH'] = f"{Path.cwd()};{env['PYTHONPATH']}"
        else:
            env['PYTHONPATH'] = str(Path.cwd())
        
        # รัน chatbot
        subprocess.run([venv_python, "chatbot_app.py"], env=env)
        
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานตามความประสงทผู้ใช้")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    run_with_venv()
