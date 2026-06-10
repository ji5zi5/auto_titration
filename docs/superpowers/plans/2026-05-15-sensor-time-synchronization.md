# Sensor Time Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add timestamp-based synchronization so Mini2 thermal ROI, visible-camera color features, and injected volume are recorded on one defensible time axis with measured sync error.

**Architecture:** Use the Mini2 thermal frame timestamp as the canonical row time. Capture visible frames in a timestamped ring buffer using the same `time.perf_counter()` clock, then pair each Mini2 frame with the nearest visible frame and record `thermal_time_s`, `visible_time_s`, `sync_offset_ms`, `sync_method`, and `sync_quality`. Keep the system software-synchronized, not hardware-triggered, and make the remaining timing error visible in CSV, summary JSON, and the web dashboard.

**Tech Stack:** Python stdlib threads/deques, existing OpenCV camera readers, existing `ColorFeatureExtractor`, CSV schema, static HTML/CSS/JS dashboard, `unittest`.

---

## File Structure

- Modify `tools/windows_live_collect.py`
  - Add timestamped visible-frame ring buffer.
  - Replace “latest visible frame” pairing with nearest-time matching.
  - Add sync CLI options and summary statistics.
- Modify `auto_titrator/data_schema.py`
  - Add canonical sync columns so CSV output and browser live CSV columns stay aligned.
- Modify `website/app.js`
  - Read/display sync fields from CSV/API.
  - Add sync warning metrics.
- Modify `website/index.html`
  - Add sync status cards/wording to the official Mini2 dashboard section.
- Modify `website/styles.css`
  - Add small sync status styling if needed.
- Modify `tests/test_windows_live_collect.py`
  - Unit-test nearest-frame matching, stale-frame warnings, and CSV sync columns.
- Modify `tests/test_data_schema.py`
  - Assert sync fields are canonical schema columns.
- Modify `tests/test_website_assets.py`
  - Assert dashboard documents and reads sync fields.
- Modify `README.md`
  - Document software synchronization and the meaning of `sync_offset_ms`.

---

## Sync Data Contract

Add these CSV fields:

```text
thermal_time_s
visible_time_s
sync_offset_ms
sync_method
sync_quality
sync_warning
```

Definitions:

```text
time_s          = canonical row time; equal to thermal_time_s for Mini2 runs
thermal_time_s  = Mini2 frame timestamp from the same PC monotonic clock
visible_time_s  = matched visible frame timestamp from the same PC monotonic clock
sync_offset_ms  = (visible_time_s - thermal_time_s) * 1000
sync_method     = nearest_visible_frame
sync_quality    = good | warning | missing
sync_warning    = empty, visible frame unavailable, or offset limit exceeded
```

Default threshold:

```text
--max-sync-offset-ms 20
```

Rows are not dropped by default. Rows with `abs(sync_offset_ms) > max_sync_offset_ms` are marked `sync_quality=warning` so analysis can exclude them.

---

### Task 1: Add canonical sync schema fields

**Files:**
- Modify: `auto_titrator/data_schema.py`
- Test: `tests/test_data_schema.py`

- [ ] **Step 1: Write failing schema test**

Add this test to `tests/test_data_schema.py`:

```python
def test_schema_contains_sensor_sync_fields(self):
    for column in [
        "thermal_time_s",
        "visible_time_s",
        "sync_offset_ms",
        "sync_method",
        "sync_quality",
        "sync_warning",
    ]:
        with self.subTest(column=column):
            self.assertIn(column, DEFAULT_COLUMNS)
```

- [ ] **Step 2: Run schema test and verify failure**

Run:

```bash
python3 -m unittest tests.test_data_schema -v
```

Expected before implementation:

```text
FAIL: test_schema_contains_sensor_sync_fields
AssertionError: 'thermal_time_s' not found in ...
```

- [ ] **Step 3: Add fields to `DEFAULT_COLUMNS`**

In `auto_titrator/data_schema.py`, insert the new fields near existing timing/frame columns, immediately after `frame_id` or adjacent to `time_s`:

```python
    "time_s",
    "frame_id",
    "thermal_time_s",
    "visible_time_s",
    "sync_offset_ms",
    "sync_method",
    "sync_quality",
    "sync_warning",
    "injected_volume_ml",
```

- [ ] **Step 4: Run schema test and verify pass**

Run:

```bash
python3 -m unittest tests.test_data_schema -v
```

Expected:

```text
OK
```

---

### Task 2: Add timestamped visible-frame buffer and nearest matching

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing unit tests for nearest matching**

Add this test helper and test to `tests/test_windows_live_collect.py`:

```python
def rgb_frame(red):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[..., 0] = red
    frame[..., 1] = 20
    frame[..., 2] = 30
    return frame


def test_timestamped_visible_buffer_returns_nearest_frame(self):
    buffer = windows_live_collect.VisibleFrameBuffer(maxlen=4)
    buffer.add(windows_live_collect.TimestampedVisibleFrame(frame_id=0, timestamp_s=0.90, frame_rgb=rgb_frame(10)))
    buffer.add(windows_live_collect.TimestampedVisibleFrame(frame_id=1, timestamp_s=1.03, frame_rgb=rgb_frame(40)))
    buffer.add(windows_live_collect.TimestampedVisibleFrame(frame_id=2, timestamp_s=1.10, frame_rgb=rgb_frame(90)))

    matched = buffer.nearest(1.00)

    self.assertIsNotNone(matched)
    self.assertEqual(matched.frame_id, 1)
    self.assertAlmostEqual(matched.timestamp_s, 1.03)
```

- [ ] **Step 2: Write failing unit test for missing visible frame**

Add:

```python
def test_timestamped_visible_buffer_returns_none_when_empty(self):
    buffer = windows_live_collect.VisibleFrameBuffer(maxlen=4)

    self.assertIsNone(buffer.nearest(1.00))
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect -v
```

Expected before implementation:

```text
AttributeError: module 'tools.windows_live_collect' has no attribute 'VisibleFrameBuffer'
```

- [ ] **Step 4: Add timestamped visible frame types**

In `tools/windows_live_collect.py`, near `CapturedMini2Frame`, add:

```python
@dataclass(frozen=True)
class TimestampedVisibleFrame:
    frame_id: int
    timestamp_s: float
    frame_rgb: np.ndarray


class VisibleFrameBuffer:
    def __init__(self, *, maxlen: int = 128) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self._frames: deque[TimestampedVisibleFrame] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, frame: TimestampedVisibleFrame) -> None:
        with self._lock:
            self._frames.append(frame)

    def latest(self) -> TimestampedVisibleFrame | None:
        with self._lock:
            if not self._frames:
                return None
            return self._frames[-1]

    def nearest(self, timestamp_s: float) -> TimestampedVisibleFrame | None:
        with self._lock:
            if not self._frames:
                return None
            return min(self._frames, key=lambda frame: abs(frame.timestamp_s - timestamp_s))
```

Also import `deque`:

```python
from collections import deque
```

- [ ] **Step 5: Run nearest-buffer tests and verify pass**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_timestamped_visible_buffer_returns_nearest_frame tests.test_windows_live_collect.WindowsLiveCollectTests.test_timestamped_visible_buffer_returns_none_when_empty -v
```

Expected:

```text
OK
```

---

### Task 3: Timestamp visible capture thread with the shared start time

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing test for visible worker timestamps**

Add a fake camera and test:

```python
class ShortVisibleCamera:
    def __init__(self):
        self.count = 0
        self.released = False

    def read_rgb(self):
        if self.count >= 2:
            raise RuntimeError("stop")
        frame = rgb_frame(20 + self.count)
        self.count += 1
        return frame

    def release(self):
        self.released = True


def test_visible_thread_stores_timestamped_frames(self):
    camera = ShortVisibleCamera()
    start = time.perf_counter()
    worker = windows_live_collect.VisibleLatestFrameThread(camera, start_time=start)
    worker.start()
    time.sleep(0.05)

    latest = worker.latest_timestamped(timeout_s=0.1)
    worker.close()

    self.assertIsNotNone(latest)
    self.assertGreaterEqual(latest.timestamp_s, 0.0)
    self.assertGreaterEqual(worker.count, 1)
```

Add imports at the top of `tests/test_windows_live_collect.py`:

```python
import time
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_visible_thread_stores_timestamped_frames -v
```

Expected before implementation:

```text
TypeError: __init__() got an unexpected keyword argument 'start_time'
```

- [ ] **Step 3: Modify `VisibleLatestFrameThread`**

Change its constructor to accept `start_time` and a `VisibleFrameBuffer`:

```python
class VisibleLatestFrameThread:
    """Continuously read visible camera frames and expose timestamped RGB frames."""

    def __init__(self, camera: Any, *, start_time: float, max_buffer: int = 128) -> None:
        self.camera = camera
        self.start_time = start_time
        self.frames = VisibleFrameBuffer(maxlen=max_buffer)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._count = 0
        self._thread = threading.Thread(target=self._loop, name="visible-capture", daemon=True)
```

Replace `latest()` with timestamp-aware accessors while keeping the old method for existing tests:

```python
    def latest_timestamped(self, *, timeout_s: float = 2.0) -> TimestampedVisibleFrame | None:
        self._ready.wait(timeout_s)
        if self._error is not None and self.frames.latest() is None:
            raise RuntimeError(f"visible camera thread failed: {self._error}") from self._error
        return self.frames.latest()

    def nearest(self, timestamp_s: float, *, timeout_s: float = 2.0) -> TimestampedVisibleFrame | None:
        self._ready.wait(timeout_s)
        if self._error is not None and self.frames.latest() is None:
            raise RuntimeError(f"visible camera thread failed: {self._error}") from self._error
        return self.frames.nearest(timestamp_s)

    def latest(self, *, timeout_s: float = 2.0) -> np.ndarray | None:
        frame = self.latest_timestamped(timeout_s=timeout_s)
        return None if frame is None else frame.frame_rgb.copy()
```

Change `_loop()` to timestamp the capture:

```python
    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                read_start = time.perf_counter()
                frame = self.camera.read_rgb()
                read_end = time.perf_counter()
                timestamp_s = ((read_start + read_end) / 2.0) - self.start_time
                captured = TimestampedVisibleFrame(self._count, timestamp_s, frame.copy())
                self.frames.add(captured)
                self._count += 1
                self._ready.set()
        except BaseException as exc:  # noqa: BLE001 - propagated if no frame is available.
            self._error = exc
            self._ready.set()
```

- [ ] **Step 4: Update worker creation**

In `run()`, change:

```python
visible_worker = VisibleLatestFrameThread(visible_camera)
```

to:

```python
visible_worker = VisibleLatestFrameThread(visible_camera, start_time=start)
```

- [ ] **Step 5: Run visible-thread test and existing windows live tests**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect -v
```

Expected:

```text
OK
```

---

### Task 4: Add sync metadata to each Windows live CSV row

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing CSV-row sync test**

In `test_run_writes_merged_visible_and_thermal_feature_rows`, after reading rows, add:

```python
self.assertIn("thermal_time_s", rows[0])
self.assertIn("visible_time_s", rows[0])
self.assertIn("sync_offset_ms", rows[0])
self.assertEqual(rows[0]["sync_method"], "nearest_visible_frame")
self.assertIn(rows[0]["sync_quality"], {"good", "warning"})
```

In `test_no_visible_mode_writes_thermal_only_rows`, add:

```python
self.assertEqual(row["sync_quality"], "missing")
self.assertEqual(row["sync_warning"], "visible frame unavailable")
```

Update the fake `Namespace` in affected tests to include:

```python
sync_method="nearest",
max_sync_offset_ms=20.0,
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect -v
```

Expected before implementation:

```text
AssertionError: 'thermal_time_s' not found in ...
```

- [ ] **Step 3: Add sync helper function**

In `tools/windows_live_collect.py`, add:

```python
def build_sync_metadata(
    *,
    thermal_time_s: float,
    visible_time_s: float | None,
    max_sync_offset_ms: float,
) -> dict[str, object]:
    if visible_time_s is None:
        return {
            "thermal_time_s": round(float(thermal_time_s), 6),
            "visible_time_s": "",
            "sync_offset_ms": "",
            "sync_method": "nearest_visible_frame",
            "sync_quality": "missing",
            "sync_warning": "visible frame unavailable",
        }
    offset_ms = (float(visible_time_s) - float(thermal_time_s)) * 1000.0
    warning = "" if abs(offset_ms) <= max_sync_offset_ms else f"sync offset exceeds {max_sync_offset_ms:g} ms"
    return {
        "thermal_time_s": round(float(thermal_time_s), 6),
        "visible_time_s": round(float(visible_time_s), 6),
        "sync_offset_ms": round(offset_ms, 6),
        "sync_method": "nearest_visible_frame",
        "sync_quality": "good" if not warning else "warning",
        "sync_warning": warning,
    }
```

- [ ] **Step 4: Use nearest visible frame in `run()`**

Replace the visible-frame section in `run()` with this shape:

```python
            visible_features: dict[str, float] = {}
            matched_visible_time_s: float | None = None
            if visible_camera is not None:
                if visible_worker is not None:
                    matched_visible = visible_worker.nearest(elapsed_s)
                    frame_rgb = None if matched_visible is None else matched_visible.frame_rgb.copy()
                    matched_visible_time_s = None if matched_visible is None else matched_visible.timestamp_s
                else:
                    read_start = time.perf_counter()
                    frame_rgb = visible_camera.read_rgb()
                    read_end = time.perf_counter()
                    matched_visible_time_s = ((read_start + read_end) / 2.0) - start
                if frame_rgb is not None:
                    if visible_roi is None:
                        visible_roi = resolve_visible_roi(args.visible_roi, frame_rgb)
                    base_visible = color_extractor.extract(frame_rgb, visible_roi, previous=previous_visible)
                    visible_features = prefix_features(base_visible, "visible")
                    previous_visible = base_visible
                    visible_frames += 1
```

After `row = sample.to_serializable_row()`, add:

```python
            row.update(
                build_sync_metadata(
                    thermal_time_s=elapsed_s,
                    visible_time_s=matched_visible_time_s,
                    max_sync_offset_ms=args.max_sync_offset_ms,
                )
            )
```

- [ ] **Step 5: Add CLI validation**

In `main()`, add arguments:

```python
    parser.add_argument("--sync-method", choices=["nearest"], default="nearest")
    parser.add_argument("--max-sync-offset-ms", type=float, default=20.0)
```

After frames validation, add:

```python
    if args.max_sync_offset_ms <= 0:
        parser.error("--max-sync-offset-ms must be positive")
```

- [ ] **Step 6: Run Windows live tests**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect -v
```

Expected:

```text
OK
```

---

### Task 5: Add sync summary statistics

**Files:**
- Modify: `tools/windows_live_collect.py`
- Test: `tests/test_windows_live_collect.py`

- [ ] **Step 1: Write failing summary test**

In `test_run_writes_merged_visible_and_thermal_feature_rows`, after loading `summary`, add:

```python
self.assertIn("sync_offset_abs_mean_ms", summary)
self.assertIn("sync_offset_abs_max_ms", summary)
self.assertIn("sync_warning_rows", summary)
self.assertEqual(summary["sync_method"], "nearest_visible_frame")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect.WindowsLiveCollectTests.test_run_writes_merged_visible_and_thermal_feature_rows -v
```

Expected before implementation:

```text
AssertionError: 'sync_offset_abs_mean_ms' not found in summary
```

- [ ] **Step 3: Add summary helper**

In `tools/windows_live_collect.py`, add:

```python
def summarize_sync(rows: list[dict[str, Any]]) -> dict[str, object]:
    offsets: list[float] = []
    warning_rows = 0
    missing_rows = 0
    for row in rows:
        if row.get("sync_quality") == "warning":
            warning_rows += 1
        if row.get("sync_quality") == "missing":
            missing_rows += 1
        value = row.get("sync_offset_ms")
        if value not in ("", None):
            offsets.append(abs(float(value)))
    return {
        "sync_method": "nearest_visible_frame",
        "sync_offset_abs_mean_ms": round(sum(offsets) / len(offsets), 6) if offsets else None,
        "sync_offset_abs_max_ms": round(max(offsets), 6) if offsets else None,
        "sync_warning_rows": warning_rows,
        "sync_missing_rows": missing_rows,
    }
```

- [ ] **Step 4: Merge sync summary into output summary**

Before writing summary JSON, change:

```python
    summary = {
```

to:

```python
    sync_summary = summarize_sync(rows)
    summary = {
```

Then add inside `summary`:

```python
        **sync_summary,
```

- [ ] **Step 5: Run tests**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect -v
```

Expected:

```text
OK
```

---

### Task 6: Show sync health in the web dashboard

**Files:**
- Modify: `website/index.html`
- Modify: `website/app.js`
- Modify: `website/styles.css`
- Test: `tests/test_website_assets.py`

- [ ] **Step 1: Write failing website asset assertions**

In `tests/test_website_assets.py`, add expected HTML strings:

```python
"센서 동기화 상태",
"sync_offset_ms",
"sync_quality",
"sync_warning",
"apiSyncOffset",
"apiSyncQuality",
```

Add expected JS strings:

```python
self.assertIn("renderSyncMetrics", js)
self.assertIn("sync_offset_ms", js)
self.assertIn("sync_quality", js)
```

- [ ] **Step 2: Run website tests and verify failure**

Run:

```bash
python3 -m unittest tests.test_website_assets -v
```

Expected before implementation:

```text
FAIL: test_static_website_documents_project_and_csv_viewer
```

- [ ] **Step 3: Add sync cards to official dashboard HTML**

In `website/index.html`, inside the official Mini2 dashboard metrics, add cards:

```html
<div class="metric"><span>센서 동기화 상태</span><strong id="apiSyncQuality">-</strong></div>
<div class="metric"><span>sync_offset_ms</span><strong id="apiSyncOffset">-</strong></div>
```

Add explanatory text near the official panel:

```html
<p class="camera-hint">
  Mini2와 일반 카메라는 같은 PC clock으로 timestamp를 찍고 가장 가까운 프레임끼리 매칭합니다.
  CSV에는 sync_offset_ms, sync_quality, sync_warning이 저장됩니다.
</p>
```

- [ ] **Step 4: Add JS sync rendering**

In `website/app.js`, add:

```javascript
function renderSyncMetrics(latest, summary) {
  const offset = Number.parseFloat(latest?.sync_offset_ms);
  const quality = latest?.sync_quality || '-';
  if ($('apiSyncQuality')) $('apiSyncQuality').textContent = quality;
  if ($('apiSyncOffset')) {
    $('apiSyncOffset').textContent = Number.isFinite(offset)
      ? `${format(offset)} ms`
      : valueOrDash(summary?.sync_offset_abs_mean_ms, ' ms avg');
  }
}
```

Call it in `renderApiPayload(payload)` after latest is computed:

```javascript
  renderSyncMetrics(latest, payload.summary);
```

In `render(rows, fileName)`, add metrics:

```javascript
metric('Sync offset', valueOrDash(last.sync_offset_ms, ' ms')),
metric('Sync quality', last.sync_quality || '-'),
```

- [ ] **Step 5: Run website tests and JS syntax check**

Run:

```bash
python3 -m unittest tests.test_website_assets -v
node --check website/app.js
```

Expected:

```text
OK
```

---

### Task 7: Document synchronization method

**Files:**
- Modify: `README.md`
- Test: `tests/test_readme_docs.py`

- [ ] **Step 1: Write failing README test**

In `tests/test_readme_docs.py`, add assertions in an existing README test or new test:

```python
def test_readme_documents_sensor_synchronization(self):
    readme = Path("README.md").read_text(encoding="utf-8")

    self.assertIn("sync_offset_ms", readme)
    self.assertIn("공통 PC clock", readme)
    self.assertIn("하드웨어 동기화", readme)
    self.assertIn("20 ms", readme)
```

Ensure `Path` is imported:

```python
from pathlib import Path
```

- [ ] **Step 2: Run README tests and verify failure**

Run:

```bash
python3 -m unittest tests.test_readme_docs -v
```

Expected before README update:

```text
FAIL: test_readme_documents_sensor_synchronization
```

- [ ] **Step 3: Add README section**

Add this section near the Mini2/dashboard documentation:

```markdown
## Sensor synchronization

Mini2 thermal frames and visible-camera frames are software-synchronized with a common PC clock, not hardware synchronization. The Mini2 frame timestamp is the canonical `time_s`. The visible-camera thread stores timestamped frames in a ring buffer, and each Mini2 frame is matched to the nearest visible frame.

Each CSV row includes:

- `thermal_time_s`
- `visible_time_s`
- `sync_offset_ms`
- `sync_method`
- `sync_quality`
- `sync_warning`

Default quality threshold is 20 ms. At 1 mL/s pump speed, 20 ms corresponds to 0.02 mL timing-related volume uncertainty. Rows above the threshold are kept but marked with `sync_quality=warning` so they can be excluded from precise analysis. This is not hardware-trigger synchronization; it is timestamp-based software synchronization suitable for the science-fair data collection system.
```

- [ ] **Step 4: Run README tests**

Run:

```bash
python3 -m unittest tests.test_readme_docs -v
```

Expected:

```text
OK
```

---

### Task 8: Full verification

**Files:**
- No new files.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
python3 -m unittest tests.test_windows_live_collect tests.test_data_schema tests.test_website_assets tests.test_readme_docs -v
```

Expected:

```text
OK
```

- [ ] **Step 2: Run full test suite**

Run:

```bash
python3 -m unittest discover -v
```

Expected:

```text
OK
```

- [ ] **Step 3: Run compile and JS syntax checks**

Run:

```bash
python3 -m compileall -q auto_titrator tests tools run.py
node --check website/app.js
```

Expected:

```text
(no output from compileall)
(no output from node --check)
```

- [ ] **Step 4: Run Windows hardware smoke when Mini2 and visible camera are connected**

Run from Windows:

```bat
launchers\windows\20_windows_live_collect.bat
```

Expected summary JSON fields:

```json
{
  "sync_method": "nearest_visible_frame",
  "sync_offset_abs_mean_ms": 0.0,
  "sync_offset_abs_max_ms": 20.0,
  "sync_warning_rows": 0
}
```

The exact values will vary. Accept the run if:

```text
sync_offset_abs_mean_ms <= 10 ms
sync_offset_abs_max_ms <= 25 ms for most rows
sync_warning_rows is small enough to explain or exclude
```

- [ ] **Step 5: Save hardware evidence**

Copy the generated CSV and summary JSON into a dated folder under:

```text
data/raw/sync_validation/
```

Use a folder name like:

```text
2026-05-15-mini2-visible-sync-smoke
```

- [ ] **Step 6: Final report note**

Record the measured average/max sync offset in `.omx/notepad.md` with:

```bash
omx notepad write-working --input '{"note":"Sensor sync smoke: mean offset <value> ms, max offset <value> ms, threshold 20 ms, pump speed assumption 1 mL/s -> 20 ms = 0.02 mL."}' --json
```

---

## Self-Review

- Spec coverage: The plan adds shared-clock timestamps, nearest-frame matching, CSV sync fields, summary stats, dashboard display, README wording, and tests.
- Placeholder scan: No task uses unresolved placeholder wording. All new fields, functions, and commands are named explicitly.
- Type consistency: `TimestampedVisibleFrame.timestamp_s`, `thermal_time_s`, `visible_time_s`, and `sync_offset_ms` are consistently named across Python, CSV, and JS.
- Scope control: This plan intentionally does not add hardware trigger sync or linear interpolation. Those can be future improvements after measuring `sync_offset_ms` distribution. The current plan produces working, testable software synchronization.
