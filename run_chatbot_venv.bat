@echo off
title Power BI Chatbot - Virtual Environment
color 0A

echo.
echo  ███████╗ █████╗ ██████╗ ███████╗██████╗ █████╗ ███████╗
echo  ██╔════╝██╔══██╗██╔════╝██╔══██╗██╔══██╗
echo  ███████╗╚██████╔╝███████╗╚██████╔╝███████╗
echo  ╚═════╝ ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
echo.
echo  🤖 Power BI Chatbot - Virtual Environment
echo ========================================

echo.
echo 🔍 ตรวจสอบ Virtual Environment...
if exist ".venv\Scripts\python.exe" (
    echo ✅ พบ Virtual Environment Python
    set PYTHON_EXE=.venv\Scripts\python.exe
) else (
    echo ❌ ไม่พบ Virtual Environment
    echo 💡 สร้าง venv: python -m venv .venv
    echo 💡 เปิด venv: .venv\Scripts\activate
    pause
    exit /b
)

echo.
echo 📦 ตรวจสอบ Dependencies...
%PYTHON_EXE% -c "import flask, werkzeug, azure.identity, msal, requests; print('✅ Dependencies พร้อม')" 2>nul
if errorlevel 1 (
    echo ❌ Dependencies ไม่พร้อม
    echo 📦 กำลังติดตั้ง...
    %PYTHON_EXE% -m pip install flask werkzeug azure-identity msal requests
    if errorlevel 1 (
        echo ❌ ติดตั้ง dependencies ล้มเหลว
        pause
        exit /b
    )
    echo ✅ ติดตั้ง dependencies สำเร็จ
)

echo.
echo 🚀 กำลังเริ่มต้น Power BI Chatbot...
echo 🐍 Python: %PYTHON_EXE%
echo 📁 App: chatbot_app.py
echo 🌐 URL: http://localhost:5000
echo 🔧 Debug Mode: ON
echo 🎯 กด Ctrl+C เพื่อหยุด
echo ========================================

echo.
echo 🎯 กำลังรัน chatbot...
%PYTHON_EXE% chatbot_app.py

echo.
echo 👋 ปิดโปรแกรม
pause
