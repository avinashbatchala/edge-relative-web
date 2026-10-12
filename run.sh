#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_ROOT"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r backend/requirements.txt
fi
if [ ! -f frontend/dist/index.html ]; then
  npm ci --prefix frontend
  npm run build --prefix frontend
fi
if [ ! -f .env ]; then cp .env.example .env; fi
exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1 --env-file .env
