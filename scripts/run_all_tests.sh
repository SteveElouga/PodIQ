#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
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
