@echo off
chcp 65001 > nul
cd /d "C:\Users\USER\OneDrive\바탕 화면\stock-gpt-server"

echo ============================================
echo Stock GPT Server 시작
echo 프로젝트 폴더: %cd%
echo ============================================

py -m uvicorn main:app --host 127.0.0.1 --port 8000

pause