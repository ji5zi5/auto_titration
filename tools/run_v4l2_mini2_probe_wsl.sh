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
import cv2
import numpy
PY
then
  echo "  opencv + numpy already installed."
else
  echo "  Installing opencv-python + numpy..."
  python -m pip install -q opencv-python numpy
fi

echo "[3.20/4] Loading/checking uvcvideo driver..."
if [[ -d /sys/bus/usb/drivers/uvcvideo ]]; then
  echo "  uvcvideo driver path exists."
else
  echo "  Running: sudo modprobe uvcvideo"
  sudo modprobe uvcvideo || true
fi

echo "[3.25/4] Finding HIK/Mini2 USB device and binding to uvcvideo for V4L2 if needed..."
FOUND_HIK_USB=0
if [[ -d /sys/bus/usb/drivers/uvcvideo ]]; then
  for device in /sys/bus/usb/devices/*; do
    [[ -f "$device/idVendor" && -f "$device/idProduct" ]] || continue
    idVendor="$(<"$device/idVendor")"
    idProduct="$(<"$device/idProduct")"
    [[ "$idVendor" == "2bdf" ]] || continue
    FOUND_HIK_USB=1
    product="$(cat "$device/product" 2>/dev/null || true)"
    manufacturer="$(cat "$device/manufacturer" 2>/dev/null || true)"
    echo "  HIK USB: sysfs=$(basename "$device") idVendor=$idVendor idProduct=$idProduct manufacturer=$manufacturer product=$product"
    for interface in "$device":*; do
      [[ -d "$interface" ]] || continue
      interface_name="$(basename "$interface")"
      interface_class="$(cat "$interface/bInterfaceClass" 2>/dev/null || true)"
      current_driver="none"
      if [[ -e "$interface/driver" ]]; then
        current_driver="$(basename "$(readlink -f "$interface/driver")")"
      fi
      echo "    interface=$interface_name class=$interface_class driver=$current_driver"
      [[ "$interface_class" == "0e" ]] || continue
      if [[ -e "$interface/driver" ]]; then
        echo "    $interface_name already bound to $(basename "$(readlink -f "$interface/driver")")"
      else
        echo "    Binding $interface_name to uvcvideo"
        echo "$interface_name" | sudo tee /sys/bus/usb/drivers/uvcvideo/bind >/dev/null || true
      fi
    done
  done
  if [[ "$FOUND_HIK_USB" == "0" ]]; then
    echo "  No HIK USB device found in WSL sysfs. attach Mini2 to WSL with usbipd first, then rerun this script."
  fi
  sleep 1
else
  echo "  uvcvideo driver path not found; continuing with existing /dev/video nodes."
fi

echo "[3.5/4] Checking /dev/video permissions..."
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
  echo "  No /dev/video nodes found in WSL. This means V4L2 cannot see Mini2 yet."
fi

echo "[4/4] Probing V4L2 formats and frames..."
python -u tools/v4l2_mini2_probe.py
