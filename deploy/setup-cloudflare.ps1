# Complete Cloudflare Tunnel binding for api.mrdev.cyou
# Requires an interactive browser login the first time.
# Usage:
#   .\deploy\setup-cloudflare.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$configExample = Join-Path $PSScriptRoot "cloudflared-config.example.yml"
$configOut = Join-Path $PSScriptRoot "cloudflared-config.yml"

$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "Installing cloudflared..."
    winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

Write-Host "Opening Cloudflare login (browser)..."
cloudflared tunnel login

$existing = cloudflared tunnel list 2>$null | Select-String "bedrock-proxy"
if (-not $existing) {
    Write-Host "Creating tunnel bedrock-proxy..."
    cloudflared tunnel create bedrock-proxy
} else {
    Write-Host "Tunnel bedrock-proxy already exists"
}

Write-Host "Routing DNS api.mrdev.cyou -> tunnel..."
cloudflared tunnel route dns bedrock-proxy api.mrdev.cyou

$tunnelLine = (cloudflared tunnel list | Select-String "bedrock-proxy" | Select-Object -First 1).ToString()
if (-not $tunnelLine) { throw "Could not find tunnel bedrock-proxy after create" }
# tunnel list columns: ID NAME ...
$tunnelId = ($tunnelLine -split "\s+")[0]
$cred = Join-Path $env:USERPROFILE ".cloudflared\$tunnelId.json"
if (-not (Test-Path $cred)) { throw "Missing credentials file: $cred" }

$content = Get-Content $configExample -Raw
$content = $content -replace "REPLACE_WITH_TUNNEL_UUID", $tunnelId
$content = $content -replace "C:\\Users\\admin\\.cloudflared\\REPLACE_WITH_TUNNEL_UUID.json", ($cred -replace "\\", "\\")
# Simpler: rewrite file
@"
tunnel: $tunnelId
credentials-file: $cred

ingress:
  - hostname: api.mrdev.cyou
    service: http://127.0.0.1:8000
    originRequest:
      connectTimeout: 30s
      http2Origin: false
  - service: http_status:404
"@ | Set-Content -Encoding utf8 $configOut

Write-Host "Wrote $configOut"
Write-Host "Start tunnel with:"
Write-Host "  cloudflared tunnel --config `"$configOut`" run"
Write-Host "Keep gateway running: .\deploy\run-gateway.ps1"
Write-Host "Then test: curl https://api.mrdev.cyou/health"
