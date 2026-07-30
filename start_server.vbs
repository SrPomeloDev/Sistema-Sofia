Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\lenov\Desktop\CAMIONES"
WshShell.Run "update-sheet-app\venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000", 0, False
