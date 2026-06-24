#!/usr/bin/env bash
# Start all TAIA development services (UI :5000, AI :8000, Mock ERP :8801)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT"
export ERP_API_BASE_URL="${ERP_API_BASE_URL:-http://127.0.0.1:8801/api/v1}"
export TAIA_API_URL="${TAIA_API_URL:-http://127.0.0.1:8000}"
export ERP_PUBLIC_URL="${ERP_PUBLIC_URL:-http://127.0.0.1:8801}"

if [ ! -d node_modules/concurrently ]; then
  npm install
fi

npm run dev
