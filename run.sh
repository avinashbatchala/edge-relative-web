#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_ROOT"

supported_python() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

if [ -d .venv ]; then
  if ! supported_python .venv/bin/python; then
    cat >&2 <<'MESSAGE'
The existing .venv uses an unsupported Python version.
This app requires Python 3.11+; Python 3.12 is recommended.

Deactivate the old environment, then run:
  mv .venv .venv-python39-backup
  python3.12 -m venv .venv
  bash run.sh

Your .env credentials and configuration stay in place.
MESSAGE
    exit 1
  fi
else
  SELECTED_PYTHON="${PYTHON_BIN:-}"

  if [ -n "$SELECTED_PYTHON" ]; then
    if ! supported_python "$SELECTED_PYTHON"; then
      echo "PYTHON_BIN must point to Python 3.11 or newer." >&2
      exit 1
    fi
  else
    for candidate in python3.12 python3.11 python3.13 python3; do
      if command -v "$candidate" >/dev/null 2>&1 &&
        supported_python "$candidate"; then
        SELECTED_PYTHON="$candidate"
        break
      fi
    done
  fi

  if [ -z "$SELECTED_PYTHON" ]; then
    echo "Install Python 3.12, then run this script again." >&2
    exit 1
  fi

  "$SELECTED_PYTHON" -m venv .venv
fi

# Install dependencies initially, after changes, or after an interrupted install.
REQUIREMENTS_HASH="$(.venv/bin/python -c '
import hashlib
from pathlib import Path
print(hashlib.sha256(Path("backend/requirements.txt").read_bytes()).hexdigest())
')"

INSTALLED_HASH=""
if [ -f .venv/.requirements-sha256 ]; then
  INSTALLED_HASH="$(cat .venv/.requirements-sha256)"
fi

if [ "$REQUIREMENTS_HASH" != "$INSTALLED_HASH" ]; then
  .venv/bin/python -m pip install -r backend/requirements.txt
  printf '%s\n' "$REQUIREMENTS_HASH" > .venv/.requirements-sha256
fi

if [ ! -f frontend/dist/index.html ]; then
  npm ci --prefix frontend
  npm run build --prefix frontend
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

exec .venv/bin/python -m uvicorn app.main:app \
  --app-dir backend \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 \
  --env-file .env