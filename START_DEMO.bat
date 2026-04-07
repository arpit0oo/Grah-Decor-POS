@echo off
echo ========================================
echo   Grah Decor POS - Public Demo Link
echo ========================================
echo.
echo Make sure START_SERVER.bat is running first!
echo.

cd /d %~dp0

set PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links

echo Starting ngrok tunnel to port 5000...
echo Share the https:// URL below with your client.
echo Press Ctrl+C to stop.
echo.

ngrok http 5000
