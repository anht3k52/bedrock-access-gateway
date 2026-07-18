@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
where pm2 >nul 2>&1
if errorlevel 1 (
  echo pm2 not installed
  exit /b 1
)
call pm2 stop mrdev-gateway mrdev-tunnel
call pm2 delete mrdev-gateway mrdev-tunnel
call pm2 save
echo Stopped MRDEV PM2 apps.
exit /b 0
