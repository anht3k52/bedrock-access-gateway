# Generate ADMIN_PASSWORD_SHA256 for deploy/.env.local
# Usage:
#   .\deploy\hash-admin-password.ps1 -Password "your-password" -Salt "mrdev-gateway-v1"

param(
    [Parameter(Mandatory = $true)]
    [string]$Password,
    [string]$Salt = "mrdev-gateway-v1"
)

$ErrorActionPreference = "Stop"
$py = @"
import hashlib
salt = r'''$Salt'''
password = r'''$Password'''
print(hashlib.sha256(f'{salt}:{password}'.encode('utf-8')).hexdigest())
"@
$hash = python -c $py
Write-Host "ADMIN_PASSWORD_SALT=$Salt"
Write-Host "ADMIN_PASSWORD_SHA256=$hash"
Write-Host ""
Write-Host "Paste those two lines into deploy/.env.local (do not store plaintext password)."
