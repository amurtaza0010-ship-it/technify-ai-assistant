# Start all TAIA development services (UI :5000, AI :8000, Mock ERP :8801)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONPATH = $Root
if (-not $env:ERP_API_BASE_URL) { $env:ERP_API_BASE_URL = "http://127.0.0.1:8801/api/v1" }
if (-not $env:TAIA_API_URL) { $env:TAIA_API_URL = "http://127.0.0.1:8000" }
if (-not $env:ERP_PUBLIC_URL) { $env:ERP_PUBLIC_URL = "http://127.0.0.1:8801" }

if (-not (Test-Path "node_modules\concurrently")) {
    npm install
}

npm run dev
