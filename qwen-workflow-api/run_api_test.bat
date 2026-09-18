@echo off
REM Quick API test on Windows
cd /d "%~dp0"
if not exist .env (
  echo Copy .env.example to .env and fill API_KEY / WORKER_KEY first.
  copy .env.example .env
  notepad .env
  exit /b 1
)
python examples\simple_test.py
pause
