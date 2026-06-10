#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1
APP_MIN_C="${APP_MIN_C:-20}"
APP_MAX_C="${APP_MAX_C:-37}"
TOLERANCE_C="${TOLERANCE_C:-2}"

echo "[1/4] Creating/reusing WSL virtualenv..."
python3 -m venv .venv-mini2

echo "[2/4] Activating virtualenv..."
# shellcheck disable=SC1091
. .venv-mini2/bin/activate

echo "[3/4] Checking Python packages..."
if python - <<'PY'
import numpy
PY
then
  echo "  numpy already installed."
else
  echo "  Installing numpy..."
  python -m pip install -q numpy
fi

echo "[4/4] Running formula research on latest detailed raw sequence..."
echo "  Using official-app bounds: min=${APP_MIN_C} C max=${APP_MAX_C} C tolerance=${TOLERANCE_C} C"
python -u tools/mini2_formula_research.py --app-min-c "$APP_MIN_C" --app-max-c "$APP_MAX_C" --tolerance-c "$TOLERANCE_C"
