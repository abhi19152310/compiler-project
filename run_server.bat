@echo off
set PYTHONPATH=%~dp0
echo Starting Text2Web editor on http://127.0.0.1:5000 ...
"%~dp0.venv\Scripts\python.exe" app.py
