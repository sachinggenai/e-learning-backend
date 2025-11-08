#!/bin/bash

# Simple dev launcher for FastAPI backend
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ ! -d "$VENV_DIR" ]; then
  echo "[backend] Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Check if uvicorn is installed
if ! python -c 'import uvicorn' 2>/dev/null; then
  echo "[backend] Installing dependencies..."
  pip install --upgrade pip
  pip install -r requirements.txt
fi

export PYTHONPATH="$ROOT_DIR"

echo "[backend] Starting FastAPI on http://$HOST:$PORT (reload enabled)"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
