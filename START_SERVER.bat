@echo off
echo ========================================
echo   Grah Decor POS - Starting Server
echo ========================================
echo.

cd /d %~dp0

call venv\Scripts\activate.bat

echo Server starting at http://127.0.0.1:5000
echo Press Ctrl+C to stop
echo.

python run.py

pause
