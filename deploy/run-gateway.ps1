# Secure local run for the public Bedrock proxy (Windows).
# Usage:
#   .\deploy\run-gateway.ps1
#   .\deploy\run-gateway.ps1 -EnvFile .\deploy\.env.local

param(
    [string]$EnvFile = (Join-Path $PSScriptRoot ".env.local"),
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $repoRoot "src"

if (Test-Path $EnvFile) {
    Write-Host "Loading env from $EnvFile"
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line.Split("=", 2)
        if ($parts.Length -ne 2) { return }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:$name" -Value $value
    }
} else {
    Write-Warning "Env file not found: $EnvFile (copy deploy\env.example to deploy\.env.local)"
}

if (-not $env:ADMIN_API_KEY -and -not $env:API_KEY) {
    throw "Set ADMIN_API_KEY and/or API_KEY before starting the gateway."
}

if (-not $env:HOST) { $env:HOST = $HostAddress }
if (-not $env:PORT) { $env:PORT = "$Port" }
if (-not $env:AWS_REGION) { $env:AWS_REGION = "us-west-2" }
if (-not $env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION = $env:AWS_REGION }

Write-Host "Starting gateway on http://$($env:HOST):$($env:PORT)"
Write-Host "Public domain target: https://api.mrdev.cyou/api/v1 (via Cloudflare Tunnel)"
Set-Location $srcDir
# --timeout-keep-alive keeps proxies from holding idle sockets forever.
python -m uvicorn api.app:app --host $env:HOST --port $env:PORT --timeout-keep-alive 30 --limit-concurrency 100
