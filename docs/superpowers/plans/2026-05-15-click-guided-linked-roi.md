# Click-Guided Linked ROI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build click/touch-guided ROI detection for both visible camera and Mini2 thermal views, link the two ROI coordinate systems, and include an optional full automatic ROI recognition mode for fixed-camera science-fair operation.

**Architecture:** Keep camera capture at 25 fps and avoid heavy ML. The stable default is click/touch-guided ROI: the browser sends seed clicks to the existing collector stream server; Python stores ROI selection state, detects a local ROI around the clicked point, updates live metadata, and overlays the new rectangles on the MJPEG frames. A separate optional auto-recognition pass can scan the visible frame and Mini2 matrix for beaker/solution candidates, but it must be confidence-gated and fall back to the last clicked/calibrated ROI instead of moving the ROI randomly.

**Tech Stack:** Python stdlib HTTP server, OpenCV already installed on Windows, NumPy, existing MJPEG/SSE stream, existing HTML/JS frontend.

---

## File Structure

- Modify `tools/windows_live_collect.py`
  - Add ROI click API endpoint on `LiveStreamHandler`.
  - Add `RoiSelectionState` shared object.
  - Add visible/thermal local ROI detector functions.
  - Use dynamic ROI state during feature extraction and stream overlays.
- Modify `website/app.js`
  - Add click/touch handlers for `visiblePreview` and `thermalPreview`.
  - Convert browser click position to source image coordinates.
  - Send ROI seed clicks to collector with `fetch()`.
- Modify `website/index.html`
  - Add small hint/status text for ROI selection mode.
- Modify `launchers/windows/20_windows_live_collect.bat`
  - Add defaults for click ROI enabled and ROI link mode.
- Modify `tests/test_windows_live_collect.py`
  - Test ROI seed parsing, visible detector fallback, thermal detector fallback, and linked mapping.
- Modify `tests/test_website_assets.py`
  - Test that the website contains click handlers and `/api/roi-click` usage.

---

### Task 1: Add ROI selection state and click request parsing

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing tests**

Add tests that expect a state object to hold independent visible and thermal ROI values and anchor points:

```python
def test_roi_selection_state_updates_visible_and_thermal_rois(self):
    state = windows_live_collect.RoiSelectionState(
        visible_roi=Roi(80, 60, 160, 120),
        thermal_roi=Roi(96, 72, 64, 48),
    )

    state.update_visible(Roi(20, 30, 80, 60), seed=(50, 60), frame_shape=(240, 320))
    state.update_thermal(Roi(100, 80, 40, 30), seed=(120, 95), frame_shape=(192, 256))

    self.assertEqual(state.visible_roi, Roi(20, 30, 80, 60))
    self.assertEqual(state.thermal_roi, Roi(100, 80, 40, 30))
    self.assertEqual(state.visible_anchor.seed_xy, (50, 60))
    self.assertEqual(state.thermal_anchor.seed_xy, (120, 95))
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_roi_selection_state_updates_visible_and_thermal_rois -v
```

Expected: fails because `RoiSelectionState` does not exist.

- [ ] **Step 3: Implement minimal state classes**

Add near the existing dataclasses in `tools/windows_live_collect.py`:

```python
@dataclass(frozen=True)
class RoiAnchor:
    seed_xy: tuple[int, int]
    roi: Roi
    frame_shape: tuple[int, int]


class RoiSelectionState:
    def __init__(self, *, visible_roi: Roi | None = None, thermal_roi: Roi | None = None) -> None:
        self._lock = threading.Lock()
        self.visible_roi = visible_roi
        self.thermal_roi = thermal_roi
        self.visible_anchor: RoiAnchor | None = None
        self.thermal_anchor: RoiAnchor | None = None

    def update_visible(self, roi: Roi, *, seed: tuple[int, int], frame_shape: tuple[int, int]) -> None:
        with self._lock:
            self.visible_roi = roi
            self.visible_anchor = RoiAnchor(seed, roi, frame_shape)

    def update_thermal(self, roi: Roi, *, seed: tuple[int, int], frame_shape: tuple[int, int]) -> None:
        with self._lock:
            self.thermal_roi = roi
            self.thermal_anchor = RoiAnchor(seed, roi, frame_shape)

    def snapshot(self) -> tuple[Roi | None, Roi | None]:
        with self._lock:
            return self.visible_roi, self.thermal_roi
```

- [ ] **Step 4: Verify GREEN**

Run the same targeted unittest. Expected: PASS.

---

### Task 2: Add fast local ROI detectors around a clicked seed

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing tests**

Add tests for deterministic fallback and bounds safety:

```python
def test_detect_visible_roi_from_seed_returns_bounded_roi(self):
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[70:170, 90:230] = 180

    roi = windows_live_collect.detect_visible_roi_from_seed(frame, seed=(150, 120))

    self.assertGreaterEqual(roi.x, 0)
    self.assertGreaterEqual(roi.y, 0)
    self.assertLessEqual(roi.x + roi.width, 320)
    self.assertLessEqual(roi.y + roi.height, 240)
    self.assertTrue(roi.x <= 150 <= roi.x + roi.width)
    self.assertTrue(roi.y <= 120 <= roi.y + roi.height)


def test_detect_thermal_roi_from_seed_returns_bounded_roi(self):
    matrix = np.full((192, 256), 5000, dtype=np.uint16)
    matrix[60:120, 100:160] = 5400

    roi = windows_live_collect.detect_thermal_roi_from_seed(matrix, seed=(130, 90))

    self.assertGreaterEqual(roi.x, 0)
    self.assertGreaterEqual(roi.y, 0)
    self.assertLessEqual(roi.x + roi.width, 256)
    self.assertLessEqual(roi.y + roi.height, 192)
    self.assertTrue(roi.x <= 130 <= roi.x + roi.width)
    self.assertTrue(roi.y <= 90 <= roi.y + roi.height)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_detect_visible_roi_from_seed_returns_bounded_roi tests.test_windows_live_collect.WindowsLiveCollectTests.test_detect_thermal_roi_from_seed_returns_bounded_roi -v
```

Expected: fails because detector functions do not exist.

- [ ] **Step 3: Implement detectors**

Add helpers in `tools/windows_live_collect.py`:

```python
def clamp_roi_to_shape(roi: Roi, shape: tuple[int, int]) -> Roi:
    h, w = shape
    x = max(0, min(int(roi.x), w - 1))
    y = max(0, min(int(roi.y), h - 1))
    width = max(1, min(int(roi.width), w - x))
    height = max(1, min(int(roi.height), h - y))
    return Roi(x, y, width, height)


def seed_center_roi(seed: tuple[int, int], shape: tuple[int, int], *, width: int, height: int) -> Roi:
    x, y = seed
    return clamp_roi_to_shape(Roi(x - width // 2, y - height // 2, width, height), shape)


def detect_visible_roi_from_seed(frame_rgb: np.ndarray, seed: tuple[int, int]) -> Roi:
    h, w = frame_rgb.shape[:2]
    fallback = seed_center_roi(seed, (h, w), width=max(40, w // 2), height=max(30, h // 2))
    try:
        import cv2
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 120)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        sx, sy = seed
        candidates = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            if x <= sx <= x + cw and y <= sy <= y + ch and cw * ch >= 200:
                candidates.append((cw * ch, Roi(x, y, cw, ch)))
        if candidates:
            roi = max(candidates, key=lambda item: item[0])[1]
            return clamp_roi_to_shape(Roi(roi.x - 8, roi.y - 8, roi.width + 16, roi.height + 16), (h, w))
    except Exception:
        return fallback
    return fallback


def detect_thermal_roi_from_seed(raw_matrix: np.ndarray, seed: tuple[int, int]) -> Roi:
    h, w = raw_matrix.shape[:2]
    sx, sy = seed
    crop = seed_center_roi(seed, (h, w), width=80, height=60)
    region = raw_matrix[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width].astype(np.float64)
    if region.size == 0 or float(np.std(region)) < 1.0:
        return seed_center_roi(seed, (h, w), width=64, height=48)
    median = float(np.median(region))
    mask = np.abs(region - median) > max(8.0, float(np.std(region)) * 0.6)
    ys, xs = np.where(mask)
    if len(xs) < 20:
        return seed_center_roi(seed, (h, w), width=64, height=48)
    x0, x1 = int(xs.min()) + crop.x, int(xs.max()) + crop.x
    y0, y1 = int(ys.min()) + crop.y, int(ys.max()) + crop.y
    if not (x0 <= sx <= x1 and y0 <= sy <= y1):
        return seed_center_roi(seed, (h, w), width=64, height=48)
    return clamp_roi_to_shape(Roi(x0 - 4, y0 - 4, x1 - x0 + 9, y1 - y0 + 9), (h, w))
```

- [ ] **Step 4: Verify GREEN**

Run the two targeted tests. Expected: PASS.

---

### Task 3: Add `/api/roi-click` to the stream server

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Add tests for request validation helper**

Use a pure helper instead of testing the HTTP handler directly:

```python
def test_parse_roi_click_payload_accepts_visible_click(self):
    payload = windows_live_collect.parse_roi_click_payload(b'{"target":"visible","x":120,"y":80}')
    self.assertEqual(payload, ("visible", 120, 80))


def test_parse_roi_click_payload_rejects_bad_target(self):
    with self.assertRaises(ValueError):
        windows_live_collect.parse_roi_click_payload(b'{"target":"bad","x":1,"y":2}')
```

- [ ] **Step 2: Verify RED**

Run the two tests. Expected: fails because helper does not exist.

- [ ] **Step 3: Implement helper and endpoint skeleton**

Add:

```python
def parse_roi_click_payload(body: bytes) -> tuple[str, int, int]:
    payload = json.loads(body.decode("utf-8"))
    target = str(payload.get("target", "")).lower()
    if target not in {"visible", "thermal"}:
        raise ValueError("target must be visible or thermal")
    x = int(payload["x"])
    y = int(payload["y"])
    if x < 0 or y < 0:
        raise ValueError("x and y must be non-negative")
    return target, x, y
```

Extend `LiveStreamHandler` with `do_POST`; for `/api/roi-click`, parse JSON and store a pending click on `RoiSelectionState`. Return JSON `{ "ok": true }` or HTTP 400.

- [ ] **Step 4: Verify helper tests**

Run targeted tests. Expected: PASS.

---

### Task 4: Apply pending clicks inside the 25fps collector loop

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Add integration-style unit test**

Test a helper that applies click to current frames:

```python
def test_apply_roi_click_updates_visible_and_thermal_state(self):
    state = windows_live_collect.RoiSelectionState()
    visible = rgb_frame(80)
    thermal = np.full((192, 256), 5000, dtype=np.uint16)

    windows_live_collect.apply_roi_click(state, target="visible", seed=(80, 60), visible_frame=visible, thermal_matrix=thermal)
    windows_live_collect.apply_roi_click(state, target="thermal", seed=(120, 90), visible_frame=visible, thermal_matrix=thermal)

    self.assertIsNotNone(state.visible_roi)
    self.assertIsNotNone(state.thermal_roi)
```

- [ ] **Step 2: Verify RED**

Run targeted test. Expected: fails because `apply_roi_click` does not exist.

- [ ] **Step 3: Implement click application**

Add:

```python
def apply_roi_click(
    state: RoiSelectionState,
    *,
    target: str,
    seed: tuple[int, int],
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
) -> None:
    if target == "visible":
        if visible_frame is None:
            raise ValueError("visible frame unavailable")
        roi = detect_visible_roi_from_seed(visible_frame, seed)
        state.update_visible(roi, seed=seed, frame_shape=visible_frame.shape[:2])
        return
    if target == "thermal":
        if thermal_matrix is None:
            raise ValueError("thermal matrix unavailable")
        roi = detect_thermal_roi_from_seed(thermal_matrix, seed)
        state.update_thermal(roi, seed=seed, frame_shape=thermal_matrix.shape[:2])
        return
    raise ValueError("target must be visible or thermal")
```

In the main loop, consume pending clicks after `preview_frame_rgb` and `parts.raw_matrix` are available, update state, then use `selected_visible_roi` and `selected_thermal_roi` for feature extraction and overlays.

- [ ] **Step 4: Verify GREEN**

Run targeted test and existing live collect tests. Expected: PASS.

---

### Task 5: Browser click/touch handlers

**Files:**
- Modify: `website/app.js`
- Modify: `website/index.html`
- Test: `tests/test_website_assets.py`

- [ ] **Step 1: Write failing website asset assertions**

Assert `app.js` contains:

```python
self.assertIn("sendRoiClick", js)
self.assertIn("/api/roi-click", js)
self.assertIn("addRoiClickHandler('visiblePreview', 'visible')", js)
self.assertIn("addRoiClickHandler('thermalPreview', 'thermal')", js)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_website_assets -v
```

Expected: fails until JS exists.

- [ ] **Step 3: Implement JS click conversion**

Add to `website/app.js`:

```javascript
async function sendRoiClick(target, x, y) {
  await fetch(`${LIVE_STREAM_BASE}/api/roi-click`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, x: Math.round(x), y: Math.round(y) }),
  });
}

function addRoiClickHandler(imageId, target) {
  const image = $(imageId);
  if (!image) return;
  image.addEventListener('click', (event) => {
    const rect = image.getBoundingClientRect();
    const naturalWidth = image.naturalWidth || rect.width;
    const naturalHeight = image.naturalHeight || rect.height;
    const x = (event.clientX - rect.left) * naturalWidth / rect.width;
    const y = (event.clientY - rect.top) * naturalHeight / rect.height;
    sendRoiClick(target, x, y).catch((error) => setWaiting(`ROI 클릭 오류 · ${error.message}`));
  });
}

addRoiClickHandler('visiblePreview', 'visible');
addRoiClickHandler('thermalPreview', 'thermal');
```

Add hint text in HTML: `화면을 클릭하면 ROI가 클릭 지점 주변으로 자동 보정됩니다.`

- [ ] **Step 4: Verify GREEN**

Run `node --check website/app.js` and `python3 -m unittest tests.test_website_assets -v`. Expected: PASS.

---

### Task 6: Basic visible-to-thermal ROI linking

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write mapping test**

```python
def test_map_visible_roi_to_thermal_uses_anchor_delta(self):
    state = windows_live_collect.RoiSelectionState()
    state.update_visible(Roi(80, 60, 160, 120), seed=(160, 120), frame_shape=(240, 320))
    state.update_thermal(Roi(96, 72, 64, 48), seed=(128, 96), frame_shape=(192, 256))

    mapped = windows_live_collect.map_visible_roi_to_thermal(
        state,
        Roi(100, 70, 80, 60),
        visible_shape=(240, 320),
        thermal_shape=(192, 256),
    )

    self.assertGreaterEqual(mapped.x, 0)
    self.assertGreaterEqual(mapped.y, 0)
    self.assertLessEqual(mapped.x + mapped.width, 256)
    self.assertLessEqual(mapped.y + mapped.height, 192)
```

- [ ] **Step 2: Verify RED**

Run targeted test. Expected: fails because mapping helper does not exist.

- [ ] **Step 3: Implement normalized/anchor mapping**

Add:

```python
def map_visible_roi_to_thermal(
    state: RoiSelectionState,
    visible_roi: Roi,
    *,
    visible_shape: tuple[int, int],
    thermal_shape: tuple[int, int],
) -> Roi:
    if state.visible_anchor is None or state.thermal_anchor is None:
        scale_x = thermal_shape[1] / visible_shape[1]
        scale_y = thermal_shape[0] / visible_shape[0]
        return clamp_roi_to_shape(
            Roi(
                round(visible_roi.x * scale_x),
                round(visible_roi.y * scale_y),
                max(1, round(visible_roi.width * scale_x)),
                max(1, round(visible_roi.height * scale_y)),
            ),
            thermal_shape,
        )
    vx0, vy0 = state.visible_anchor.seed_xy
    tx0, ty0 = state.thermal_anchor.seed_xy
    scale_x = thermal_shape[1] / visible_shape[1]
    scale_y = thermal_shape[0] / visible_shape[0]
    visible_center_x = visible_roi.x + visible_roi.width / 2
    visible_center_y = visible_roi.y + visible_roi.height / 2
    thermal_center_x = tx0 + (visible_center_x - vx0) * scale_x
    thermal_center_y = ty0 + (visible_center_y - vy0) * scale_y
    return clamp_roi_to_shape(
        Roi(
            round(thermal_center_x - visible_roi.width * scale_x / 2),
            round(thermal_center_y - visible_roi.height * scale_y / 2),
            max(1, round(visible_roi.width * scale_x)),
            max(1, round(visible_roi.height * scale_y)),
        ),
        thermal_shape,
    )
```

When visible ROI is updated and `--roi-link-mode anchor` is enabled, update thermal ROI using this mapping unless the user has just clicked thermal directly.

- [ ] **Step 4: Verify GREEN**

Run mapping test and Windows live collect suite. Expected: PASS.

---

### Task 7: Launcher defaults and final validation

**Files:**
- Modify: `launchers/windows/20_windows_live_collect.bat`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Add launcher test expectations**

Assert these defaults exist:

```python
self.assertIn('set "ROI_CLICK_ENABLED=1"', launcher)
self.assertIn('set "ROI_LINK_MODE=anchor"', launcher)
self.assertIn('--roi-click-enabled %ROI_CLICK_ENABLED%', launcher)
self.assertIn('--roi-link-mode %ROI_LINK_MODE%', launcher)
```

- [ ] **Step 2: Implement CLI args**

Add parser args:

```python
parser.add_argument("--roi-click-enabled", type=int, default=1)
parser.add_argument("--roi-link-mode", choices=["off", "anchor"], default="anchor")
```

Add BAT defaults and pass-through.

- [ ] **Step 3: Run verification**

Run:

```bash
node --check website/app.js
python3 -m unittest tests.test_windows_live_collect tests.test_website_assets -v
python3 -m unittest discover -v
```

Expected: all tests pass; one OpenCV JPEG test may skip on WSL if `cv2` is unavailable.

- [ ] **Step 4: Sync to Windows runtime and smoke test**

Run the existing rsync copy to:

```text
C:\Users\Jio\Downloads\auto_titration_20260513-170048
```

Then run Windows targeted tests:

```powershell
py -3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_windows_live_collect_launcher_uses_auto_mini2_index_by_default -v
```

Expected: PASS.


---

### Task 8: Optional full automatic ROI recognition mode

**Files:**
- Modify: `tools/windows_live_collect.py`
- Modify: `launchers/windows/20_windows_live_collect.bat`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing tests for confidence-gated auto ROI**

Add tests that require auto recognition to return a candidate only when confidence is high enough, and to keep the previous ROI when confidence is low:

```python
def test_auto_detect_visible_roi_finds_clear_container_candidate(self):
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[55:190, 95:225] = 170
    frame[80:175, 115:205] = 210

    result = windows_live_collect.auto_detect_visible_roi(frame)

    self.assertIsNotNone(result.roi)
    self.assertGreaterEqual(result.confidence, 0.5)
    self.assertLessEqual(result.roi.x + result.roi.width, 320)
    self.assertLessEqual(result.roi.y + result.roi.height, 240)


def test_auto_detect_thermal_roi_rejects_flat_matrix(self):
    matrix = np.full((192, 256), 5000, dtype=np.uint16)

    result = windows_live_collect.auto_detect_thermal_roi(matrix)

    self.assertIsNone(result.roi)
    self.assertLess(result.confidence, 0.5)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_auto_detect_visible_roi_finds_clear_container_candidate tests.test_windows_live_collect.WindowsLiveCollectTests.test_auto_detect_thermal_roi_rejects_flat_matrix -v
```

Expected: fails because `auto_detect_visible_roi`, `auto_detect_thermal_roi`, and the result type do not exist.

- [ ] **Step 3: Add result type and visible auto detector**

Add near ROI helpers:

```python
@dataclass(frozen=True)
class RoiDetectionResult:
    roi: Roi | None
    confidence: float
    reason: str


def auto_detect_visible_roi(frame_rgb: np.ndarray) -> RoiDetectionResult:
    h, w = frame_rgb.shape[:2]
    try:
        import cv2
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 35, 110)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[float, Roi]] = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            area = cw * ch
            if area < (w * h) * 0.03:
                continue
            aspect = cw / max(1, ch)
            if not 0.35 <= aspect <= 2.2:
                continue
            center_score = 1.0 - min(1.0, abs((x + cw / 2) - w / 2) / (w / 2))
            size_score = min(1.0, area / max(1.0, (w * h) * 0.25))
            score = 0.65 * size_score + 0.35 * center_score
            candidates.append((score, clamp_roi_to_shape(Roi(x - 8, y - 8, cw + 16, ch + 16), (h, w))))
        if not candidates:
            return RoiDetectionResult(None, 0.0, "no_visible_candidate")
        score, roi = max(candidates, key=lambda item: item[0])
        if score < 0.5:
            return RoiDetectionResult(None, score, "visible_confidence_low")
        return RoiDetectionResult(roi, round(float(score), 6), "visible_contour")
    except Exception as exc:
        return RoiDetectionResult(None, 0.0, f"visible_detector_error:{exc}")
```

- [ ] **Step 4: Add thermal auto detector**

Add:

```python
def auto_detect_thermal_roi(raw_matrix: np.ndarray) -> RoiDetectionResult:
    h, w = raw_matrix.shape[:2]
    matrix = raw_matrix.astype(np.float64)
    spread = float(np.percentile(matrix, 95) - np.percentile(matrix, 5))
    if spread < 12.0:
        return RoiDetectionResult(None, 0.0, "thermal_flat")
    high = np.percentile(matrix, 75)
    low = np.percentile(matrix, 25)
    mask = np.logical_or(matrix >= high, matrix <= low)
    ys, xs = np.where(mask)
    if len(xs) < 100:
        return RoiDetectionResult(None, 0.0, "thermal_candidate_too_small")
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    roi = clamp_roi_to_shape(Roi(x0, y0, x1 - x0 + 1, y1 - y0 + 1), (h, w))
    area_ratio = (roi.width * roi.height) / max(1, w * h)
    confidence = min(1.0, spread / 80.0) * min(1.0, area_ratio / 0.35)
    if confidence < 0.5:
        return RoiDetectionResult(None, round(float(confidence), 6), "thermal_confidence_low")
    return RoiDetectionResult(roi, round(float(confidence), 6), "thermal_distribution")
```

- [ ] **Step 5: Add auto mode policy**

Add CLI options:

```python
parser.add_argument("--roi-auto-detect", choices=["off", "visible", "thermal", "both"], default="off")
parser.add_argument("--roi-auto-min-confidence", type=float, default=0.5)
parser.add_argument("--roi-auto-every", type=int, default=25)
```

Policy inside the collector loop:

```text
Every roi_auto_every frames:
  - If auto mode includes visible, run visible auto detector on latest visible frame.
  - If result confidence >= threshold, update visible ROI.
  - If auto mode includes thermal, run thermal auto detector on raw Mini2 matrix.
  - If result confidence >= threshold, update thermal ROI.
  - If confidence is low, keep previous ROI unchanged.
```

This prevents the rectangle from jumping around when the detector is unsure.

- [ ] **Step 6: Launcher defaults**

Keep automatic recognition disabled by default, but make it easy to enable for tests/demo:

```bat
if "%ROI_AUTO_DETECT%"=="" set "ROI_AUTO_DETECT=off"
if "%ROI_AUTO_MIN_CONFIDENCE%"=="" set "ROI_AUTO_MIN_CONFIDENCE=0.5"
if "%ROI_AUTO_EVERY%"=="" set "ROI_AUTO_EVERY=25"
```

Pass through:

```bat
--roi-auto-detect %ROI_AUTO_DETECT% ^
--roi-auto-min-confidence %ROI_AUTO_MIN_CONFIDENCE% ^
--roi-auto-every %ROI_AUTO_EVERY% ^
```

- [ ] **Step 7: Verification and demo criteria**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect -v
python3 -m unittest discover -v
```

Then manually test two modes on Windows:

```bat
set ROI_AUTO_DETECT=off
21_open_dashboard_server.bat
```

Expected: click-guided ROI works and does not move by itself.

```bat
set ROI_AUTO_DETECT=both
21_open_dashboard_server.bat
```

Expected: ROI moves only when confidence is high; otherwise the previous ROI remains. If it jumps on reflections/background, keep `ROI_AUTO_DETECT=off` for the final presentation and describe auto recognition as an experimental mode.


## Self-Review

- Spec coverage: visible click ROI, thermal click ROI, linked ROI mapping, optional full automatic ROI recognition, frontend click handling, launcher defaults, and validation are covered.
- Placeholder scan: no `TBD`, no vague later work, no unbounded “add tests” instruction.
- Type consistency: `Roi`, `RoiSelectionState`, `RoiAnchor`, `RoiDetectionResult`, `detect_visible_roi_from_seed`, `detect_thermal_roi_from_seed`, `auto_detect_visible_roi`, `auto_detect_thermal_roi`, `apply_roi_click`, and `map_visible_roi_to_thermal` names are used consistently.
- Risk: single-anchor linking is approximate. It is acceptable only when visible camera and Mini2 are fixed. Full automatic ROI recognition can jump on reflections/background, so it is confidence-gated and disabled by default. For higher accuracy later, add 2-point or 4-point calibration.
