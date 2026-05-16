#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer venv at repo root when no explicit PYTHON override
if [ -z "${PYTHON:-}" ] && [ -x "$ROOT/venv/bin/python3" ]; then
  PY="$ROOT/venv/bin/python3"
else
  PY="${PYTHON:-python3}"
fi
run() {
  local dir="$1"
  shift
  echo "==> $dir"
  (cd "$ROOT/$dir" && exec "$PY" -m pytest "$@")
}
run services/gateway -v
run services/analyzer-service -v
run services/ai-service -v
run services/auth-service -v
