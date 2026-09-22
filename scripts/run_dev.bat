@echo off
echo Starting PRISM Agentic Code Intelligence backend server...
python -m pytest backend/tests -v
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
