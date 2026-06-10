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

echo "[3.5/5] Checking /dev/video access..."
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
  echo "No /dev/video nodes found. Reconnect Mini2 or run the USB attach helper, then rerun 13."
  exit 1
fi

echo "[4/5] Running detailed Mini2 raw evidence test..."
echo "  Captures multiple 256x344 yuyv422 frames."
echo "  Produces exact raw stats and metadata candidate deltas."
echo "  Does NOT claim calibrated Celsius."
python -u tools/mini2_detailed_raw_test.py --capture-device /dev/video0 --frame-count 10 --delay-s 0.5 --threshold 8

echo "[5/5] Done. Open data/mini2_detailed_raw_test/*/READ_ME_FIRST.txt first."
