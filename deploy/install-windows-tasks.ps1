# Register Windows Task Scheduler jobs for gateway + cloudflared.
# Run once in an elevated PowerShell:
#   .\deploy\install-windows-tasks.ps1

param(
    [string]$PythonExe = (Get-Command python).Source,
    [string]$CloudflaredExe = "cloudflared"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runGateway = Join-Path $PSScriptRoot "run-gateway.ps1"
$tunnelConfig = Join-Path $PSScriptRoot "cloudflared-config.yml"

if (-not (Test-Path $runGateway)) { throw "Missing $runGateway" }
if (-not (Test-Path $tunnelConfig)) {
    Write-Warning "Missing $tunnelConfig — create it from cloudflared-config.example.yml before enabling the tunnel task."
}

$gatewayAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runGateway`""
$gatewayTrigger = New-ScheduledTaskTrigger -AtLogOn
$gatewaySettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "BedrockAccessGateway" -Action $gatewayAction -Trigger $gatewayTrigger -Settings $gatewaySettings -Force | Out-Null
Write-Host "Registered Task: BedrockAccessGateway"

if (Test-Path $tunnelConfig) {
    $tunnelAction = New-ScheduledTaskAction -Execute $CloudflaredExe -Argument "tunnel --config `"$tunnelConfig`" run"
    Register-ScheduledTask -TaskName "BedrockCloudflaredTunnel" -Action $tunnelAction -Trigger $gatewayTrigger -Settings $gatewaySettings -Force | Out-Null
    Write-Host "Registered Task: BedrockCloudflaredTunnel"
}

Write-Host @"

Next:
1. Rotate any AWS keys that were pasted into chat (IAM Console -> Users -> Security credentials).
2. Prefer AWS shared credentials: aws configure  (writes %USERPROFILE%\.aws\credentials)
3. Copy deploy\env.example -> deploy\.env.local and set ADMIN_API_KEY
4. Start once manually: .\deploy\run-gateway.ps1
5. Finish Cloudflare tunnel setup (see docs\Public_Proxy.md)
"@
