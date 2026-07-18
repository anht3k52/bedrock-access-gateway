@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0start-pm2.bat"
exit /b %ERRORLEVEL%
