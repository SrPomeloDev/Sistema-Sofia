@echo off
cd /d "C:\Users\lenov\Desktop\CAMIONES"
"update-sheet-app\venv\Scripts\uvicorn" main:app --reload
pause
