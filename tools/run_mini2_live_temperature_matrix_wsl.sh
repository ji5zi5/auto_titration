#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

FRAMES="${FRAMES:-25}"
FRAME_RATE_HZ="${FRAME_RATE_HZ:-25}"
ROI="${ROI:-96,72,64,48}"
OUTPUT="${OUTPUT:-data/raw/mini2-live-temperature-features.csv}"
OFFICIAL_BATCH_SIZE="${OFFICIAL_BATCH_SIZE:-1}"
if [[ -z "${OFFICIAL_DLL_DIR:-}" && -f "vendor/hikmicro_analyzer/MTlib_OL.dll" ]]; then
  OFFICIAL_DLL_DIR="$(wslpath -w "vendor/hikmicro_analyzer" 2>/dev/null || printf '%s' "vendor/hikmicro_analyzer")"
else
  OFFICIAL_DLL_DIR="${OFFICIAL_DLL_DIR:-C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer}"
fi
OFFICIAL_JPEG="${OFFICIAL_JPEG:-}"
CONVERTER_ARGS=()

if [[ -n "${OFFICIAL_WORKER_COMMAND:-}" ]]; then
  CONVERTER_ARGS+=(--official-worker-command "$OFFICIAL_WORKER_COMMAND")
  if [[ -n "${OFFICIAL_JPEG:-}" ]]; then
    CONVERTER_ARGS+=(--official-jpeg "$OFFICIAL_JPEG")
  fi
elif [[ -n "$OFFICIAL_JPEG" ]]; then
  DEFAULT_WORKER_COMMAND="py.exe -3 tools/mini2_official_mtlib_worker_win.py --metadata-jpeg \"$OFFICIAL_JPEG\" --dll-dir \"$OFFICIAL_DLL_DIR\" --batch-size $OFFICIAL_BATCH_SIZE"
  CONVERTER_ARGS+=(--official-worker-command "$DEFAULT_WORKER_COMMAND" --official-jpeg "$OFFICIAL_JPEG")
elif [[ -f "data/fixtures/mini2/IR_00001.jpeg" ]]; then
  OFFICIAL_JPEG="data/fixtures/mini2/IR_00001.jpeg"
  DEFAULT_WORKER_COMMAND="py.exe -3 tools/mini2_official_mtlib_worker_win.py --metadata-jpeg \"$OFFICIAL_JPEG\" --dll-dir \"$OFFICIAL_DLL_DIR\" --batch-size $OFFICIAL_BATCH_SIZE"
  CONVERTER_ARGS+=(--official-worker-command "$DEFAULT_WORKER_COMMAND" --official-jpeg "$OFFICIAL_JPEG")
elif [[ -n "${AFFINE_JSON:-}" ]]; then
  CONVERTER_ARGS+=(--affine-json "$AFFINE_JSON")
elif [[ -n "${LOOKUP_CSV:-}" ]]; then
  CONVERTER_ARGS+=(--lookup-csv "$LOOKUP_CSV")
elif [[ -n "${SLOPE_C_PER_RAW:-}" && -n "${INTERCEPT_C:-}" ]]; then
  CONVERTER_ARGS+=(--slope-c-per-raw "$SLOPE_C_PER_RAW" --intercept-c "$INTERCEPT_C")
else
  echo "No raw->Celsius converter was supplied."
  echo "Official path:"
  echo "  OFFICIAL_JPEG=data/fixtures/mini2/IR_00001.jpeg"
  echo "  optional OFFICIAL_WORKER_COMMAND='py.exe -3 tools/mini2_official_mtlib_worker_win.py --metadata-jpeg ...'"
  echo "Approximate affine/lookup options are intentionally not the default."
  exit 2
fi

echo "[1/5] Creating/reusing WSL Mini2 virtualenv..."
python3 -m venv .venv-mini2

# shellcheck disable=SC1091
echo "[2/5] Activating virtualenv..."
. .venv-mini2/bin/activate

echo "[3/5] Checking Python packages..."
if python - <<'PY'
import numpy
PY
then
  echo "  numpy already installed."
else
  echo "  Installing numpy..."
  python -m pip install -q numpy
fi

echo "[3.5/5] Checking Mini2 /dev/video access..."
FOUND_VIDEO_NODE=0
if command -v usbipd.exe >/dev/null 2>&1; then
  echo "  Auto-attaching HIKMICRO Mini2 to WSL if needed..."
  MINI2_BUSID="$(usbipd.exe list 2>/dev/null | awk 'tolower($0) ~ /2bdf:0102/ {print $1; exit}')"
  if [[ -n "$MINI2_BUSID" ]]; then
    usbipd.exe attach --wsl --busid "$MINI2_BUSID" >/dev/null 2>&1 || true
    sleep 1
  fi
fi
for node in /dev/video*; do
  [[ -e "$node" ]] || continue
  FOUND_VIDEO_NODE=1
  if [[ ! -w "$node" ]]; then
    if command -v wsl.exe >/dev/null 2>&1; then
      echo "  Running: wsl.exe -u root -- chmod a+rw /dev/video*"
      wsl.exe -u root -- bash -lc 'chmod a+rw /dev/video* 2>/dev/null || true'
    else
      echo "  Running: sudo chmod a+rw $node"
      sudo chmod a+rw "$node"
    fi
  fi
  ls -l "$node"
done
if [[ "$FOUND_VIDEO_NODE" == "0" ]]; then
  echo "No /dev/video nodes found. attach Mini2 to WSL with usbipd first."
  exit 1
fi

echo "[4/5] Running live 25fps Mini2 raw->Celsius matrix feature probe..."
echo "  frames=$FRAMES fps=$FRAME_RATE_HZ roi=$ROI output=$OUTPUT"
echo "  converter=${CONVERTER_ARGS[*]}"
python -u tools/mini2_live_temperature_matrix.py \
  --device /dev/video0 \
  --frames "$FRAMES" \
  --frame-rate-hz "$FRAME_RATE_HZ" \
  --roi "$ROI" \
  --output "$OUTPUT" \
  "${CONVERTER_ARGS[@]}"

echo "[5/5] Done. CSV contains scalar ROI/full-matrix features, not full matrix CSV."
