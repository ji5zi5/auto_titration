#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

echo "[1/5] Creating/reusing WSL virtualenv..."
python3 -m venv .venv-mini2

echo "[2/5] Activating virtualenv..."
# shellcheck disable=SC1091
. .venv-mini2/bin/activate

echo "[3/5] Checking Python packages..."
if python - <<'PY'
import cv2
import numpy
PY
then
  echo "  opencv + numpy already installed."
else
  echo "  Installing opencv-python + numpy..."
  python -m pip install -q opencv-python numpy
fi

echo "[3.5/5] Checking Mini2 V4L2 access..."
if [[ -d /sys/bus/usb/drivers/uvcvideo ]]; then
  sudo modprobe uvcvideo || true
fi

FOUND_VIDEO_NODE=0
for node in /dev/video*; do
  [[ -e "$node" ]] || continue
  FOUND_VIDEO_NODE=1
  if [[ ! -w "$node" ]]; then
    echo "  Running: sudo chmod a+rw $node"
    sudo chmod a+rw "$node"
  fi
  ls -l "$node"
done

if [[ "$FOUND_VIDEO_NODE" == "0" ]]; then
  echo "No /dev/video nodes found. Run 10 or reconnect Mini2, then rerun 12."
  exit 1
fi

echo "[4/5] Capturing 256x344 UVC raw frame and extracting top 256x192 matrix candidate..."
echo "  This is raw uint16 candidate data, not calibrated Celsius yet."
python -u tools/mini2_uvc_matrix_probe.py --capture-device /dev/video0 --input-format yuyv422 --width 256 --height 344 --matrix-height 192

echo "[5/5] Done. Check data/mini2_uvc_matrix_probe/*/summary.json and mini2_raw_matrix_candidate.csv"
