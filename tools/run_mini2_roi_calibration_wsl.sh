#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

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

POINTS_CSV="${POINTS_CSV:-data/mini2_roi_calibration/calibration_points.csv}"

echo "[4/4] Running ROI calibration from same-scene points..."
echo "  Points CSV: ${POINTS_CSV}"
python -u tools/mini2_roi_calibration.py --points-csv "$POINTS_CSV"
