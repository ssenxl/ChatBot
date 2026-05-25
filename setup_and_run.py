#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Power BI Chatbot - Setup and Run
สคริปต์สำหรับตั้งค่าและรัน chatbot อัตโนมัติ
"""

import os
import sys
import subprocess
import importlib.util

def check_and_install_package(package_name):
    """ตรวจสอบและติดตั้ง package ถ้ายังไม่มี"""
    try:
        importlib.import_module(package_name)
        print(f"✅ {package_name} พร้อมใช้งาน")
        return True
    except ImportError:
        print(f"❌ {package_name} ยังไม่ได้ติดตั้ง")
        print(f"📦 กำลังติดตั้ง {package_name}...")
        
        try:
            result = subprocess.run([
                sys.executable, "-m", "pip", "install", package_name
            ], capture_output=True, text=True, check=True)
            
            if result.returncode == 0:
                print(f"✅ {package_name} ติดตั้งสำเร็จ")
                return True
            else:
                print(f"❌ ติดตั้ง {package_name} ล้มเหลว: {result.stderr}")
                return False
        except subprocess.CalledProcessError as e:
            print(f"❌ ติดตั้ง {package_name} ล้มเหลว: {e}")
            return False

def setup_environment():
    """ตั้งค่า environment และติดตั้ง dependencies"""
    print("🤖 Power BI AI Assistant - Setup & Run")
    print("=" * 60)
    
    # ตรวจสอบ Python version
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"🐍 Python Version: {python_version}")
    
    # ตรวจสอบ working directory
    current_dir = os.getcwd()
    print(f"📁 Working Directory: {current_dir}")
    
    # รายการ packages ที่ต้องการ
    required_packages = [
        ("flask", "Flask - Web Framework"),
        ("werkzeug", "Werkzeug - WSGI Utilities"),
        ("azure-identity", "Azure Identity - Authentication"),
        ("msal", "MSAL - Microsoft Authentication Library"),
        ("requests", "Requests - HTTP Library")
    ]
    
    print("\n📦 ตรวจสอบและติดตั้ง Dependencies:")
    print("-" * 40)
    
    all_installed = True
    for package_name, description in required_packages:
        if not check_and_install_package(package_name):
            all_installed = False
    
    print("-" * 40)
    
    if all_installed:
        print("✅ ทุก dependencies พร้อมใช้งาน")
    else:
        print("❌ บาง dependencies ติดตั้งไม่สำเร็จ")
        print("💡 กรุณาตรวจสอบ error ข้างต้น")
        return False
    
    return True

def run_chatbot():
    """รัน chatbot application"""
    print("\n🚀 กำลังเริ่มต้น Power BI Chatbot...")
    print("=" * 60)
    
    app_file = "chatbot_app.py"
    
    # ตรวจสอบว่ามีไฟล์ chatbot_app.py
    if not os.path.exists(app_file):
        print(f"❌ ไม่พบไฟล์: {app_file}")
        print("💡 กรุณาตรวจสอบว่าไฟล์อยู่ในโฟลเดอร์ปัจจุบัน")
        return False
    
    try:
        # เพิ่ม current directory ใน Python path
        sys.path.insert(0, os.getcwd())
        
        print(f"📁 App File: {app_file}")
        print("🌐 URL: http://localhost:5000")
        print("🔧 Debug Mode: ON")
        print("🎯 กด Ctrl+C เพื่อหยุดการทำงาน")
        print("=" * 60)
        
        # รัน chatbot
        subprocess.run([sys.executable, app_file], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"❌ เกิดข้อผิดพลาดในการรัน chatbot: {e}")
        return False
    except KeyboardInterrupt:
        print("\n👋 หยุดการทำงานตามความประสงทผู้ใช้")
        return True

def main():
    """ฟังก์ชันหลัก"""
    print("🎯 Power BI AI Assistant - Auto Setup & Run")
    print("📋 สคริปต์นี้จะ:\n   1. ตรวจสอบ Python version\n   2. ติดตั้ง dependencies อัตโนมัติ\n   3. รัน chatbot application")
    print()
    
    # ตั้งค่า environment
    if not setup_environment():
        print("\n❌ Setup ล้มเหลว ไม่สามารถรัน chatbot")
        input("กด Enter เพื่อออก...")
        return
    
    # รัน chatbot
    run_chatbot()

if __name__ == "__main__":
    main()
