@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title MRDEV Gateway Launcher
echo ============================================
echo   MRDEV Bedrock Gateway - Secure Start
echo ============================================
echo.

set "ENV_FILE=%~dp0deploy\.env.local"
set "RUN_PS1=%~dp0deploy\run-gateway.ps1"
set "CF_CFG=%USERPROFILE%\.cloudflared\config.yml"
set "CF_CFG_ALT=%~dp0deploy\cloudflared-config.yml"

if not exist "%ENV_FILE%" (
  echo [ERROR] Missing %ENV_FILE%
  echo Copy deploy\env.example to deploy\.env.local and fill secrets.
  pause
  exit /b 1
)

findstr /B /C:"ADMIN_PASSWORD_SHA256=" "%ENV_FILE%" >nul
if errorlevel 1 (
  echo [ERROR] ADMIN_PASSWORD_SHA256 missing in .env.local
  echo Do not store plaintext ADMIN_PASSWORD in production.
  pause
  exit /b 1
)

findstr /I /C:"ENABLE_LEGACY_API_KEY=true" "%ENV_FILE%" >nul
if not errorlevel 1 (
  echo [WARN] ENABLE_LEGACY_API_KEY=true — shared key bypass is ON. Prefer false.
)

echo [1/3] Starting Bedrock gateway on 127.0.0.1:8000 ...
start "MRDEV-Gateway" /D "%~dp0" powershell -NoProfile -ExecutionPolicy Bypass -File "%RUN_PS1%"

timeout /t 3 /nobreak >nul

echo [2/3] Checking local health ...
powershell -NoProfile -Command "try { $r=Invoke-RestMethod -Uri http://127.0.0.1:8000/health -TimeoutSec 5; if($r.status -eq 'OK'){ Write-Host '[OK] Gateway healthy' } else { Write-Host '[WARN] Unexpected health' } } catch { Write-Host '[WARN] Gateway not ready yet — check MRDEV-Gateway window' }"

echo [3/3] Cloudflare Tunnel (reverse proxy) ...
where cloudflared >nul 2>&1
if errorlevel 1 (
  echo [SKIP] cloudflared not in PATH. Install via deploy\setup-cloudflare.ps1
) else (
  if exist "%CF_CFG%" (
    start "MRDEV-Cloudflared" cloudflared tunnel --config "%CF_CFG%" run
    echo [OK] cloudflared started with %CF_CFG%
  ) else if exist "%CF_CFG_ALT%" (
    start "MRDEV-Cloudflared" cloudflared tunnel --config "%CF_CFG_ALT%" run
    echo [OK] cloudflared started with %CF_CFG_ALT%
  ) else (
    echo [SKIP] No cloudflared config found.
    echo        Expected: %CF_CFG%
    echo        Or:       %CF_CFG_ALT%
  )
)

echo.
echo --------------------------------------------
echo  Local UI : http://127.0.0.1:8000/
echo  Admin    : http://127.0.0.1:8000/#/admin/login
echo  Usage    : http://127.0.0.1:8000/#/usage
echo  Public   : https://api.mrdev.cyou/
echo --------------------------------------------
echo  Security: SHA-256 admin password, legacy key OFF,
echo            OpenAPI hidden, localhost bind only.
echo  API without Bearer bag_... key = 401/403.
echo --------------------------------------------
echo.
pause
endlocal
