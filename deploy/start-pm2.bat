@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

echo === MRDEV Gateway: install/start with PM2 ===

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found. Install from https://nodejs.org/
  exit /b 1
)

where pm2 >nul 2>&1
if errorlevel 1 (
  echo Installing pm2 globally...
  call npm install -g pm2
  if errorlevel 1 (
    echo [ERROR] npm install -g pm2 failed
    exit /b 1
  )
)

if not exist "deploy\.env.local" (
  echo [ERROR] Missing deploy\.env.local — copy from deploy\env.example
  exit /b 1
)
if not exist "deploy\cloudflared-config.yml" (
  echo [ERROR] Missing deploy\cloudflared-config.yml
  exit /b 1
)

echo Stopping leftover uvicorn / cloudflared (manual Cursor shells)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn api.app:app' -or ($_.Name -eq 'cloudflared.exe' -and $_.CommandLine -match 'cloudflared-config') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

echo Starting PM2 apps...
call pm2 delete mrdev-gateway mrdev-tunnel >nul 2>&1
call pm2 start deploy\ecosystem.config.cjs
if errorlevel 1 (
  echo [ERROR] pm2 start failed
  exit /b 1
)

call pm2 save
echo.
call pm2 status
echo.
echo Gateway:  http://127.0.0.1:8000/health
echo Public:   https://api.mrdev.cyou/health
echo Logs:     pm2 logs
echo Restart:  deploy\restart-pm2.bat
echo Stop:     deploy\stop-pm2.bat
echo.
echo Tip: after reboot run this .bat again, or once:  pm2 startup  then  pm2 save
exit /b 0
