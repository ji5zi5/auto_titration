# Windows camera capture ON/OFF — 2026-09-14

## Delivered behavior
- Full dashboard has a camera ON/OFF button. Compact pump remote and native Android keep their existing controls; no APK was rebuilt.
- OFF is a queued acquisition-loop operation, not merely hidden previews: close both capture workers/device handles and the thermal converter, clear preview caches, and skip frame conversion, features, inference and row processing while stopped. Repeated OFF does not repeatedly close devices.
- ON opens fresh sources. The visible stream starts before the Mini2 reconnect probe. Previously selected ROI geometry is retained but unlocked for confirmation before recording.
- Recording/finalization and pending stop intent reject power changes under the same control lock as CSV start. CSV start rejects OFF, transition and error states. A known running a/b pump command also prevents OFF.
- Transition or close errors are reported, never labeled successfully OFF. Partial failed startup is cleaned up before another attempt.
- Recording frame-rate setting and lossless recording FIFO are unchanged (25 fps target). No automatic low-FPS recording mode was introduced.
- Mini2 reconnect probes exclude the active visible-camera index. Visible-only pacing does not burst to catch up after a pause. Converter teardown errors do not terminate the visible stream.
- Browser power state follows backend confirmation, prevents duplicate clicks and stale backend responses, disconnects/reconnects preview URLs, and blocks stale-frame ROI selection while OFF. Unsupported backends/native bridges do not expose a working power toggle.

## Validation
- `tests.test_camera_power`: 8 passing tests, including real capture-thread integration with fake devices. Three OFF iterations had identical read counters, no feature-analysis calls, released handles, and fresh sources on restart.
- Existing collector + dashboard: 201 tests passed; includes visible streaming independent of Mini2/analysis and recording preservation.
- Website/navigation: 16 tests passed. All 13 Node suites passed, including power transition, recording, preview and response-fence checks.
- Intercepted Chromium checks at 375/768/1024/1440 passed, including explicit power toggle, no preview src while OFF, restored full-view URLs, disabled recording, and native exclusion. Screenshot fixtures are not experiment results.
- Python compilation, JS syntax, and diff whitespace checks passed. No configured mypy/ruff or TypeScript setup was available; no such checks are claimed.

## Actual Windows check
The existing local services were restarted only after two checks confirmed recording=false, finalizing=false, and pump disconnected, and after validating exact listening process identities. Command-line configuration and ports were preserved. No pump command was sent.

See `windows_power_cycle.json`: ON -> OFF -> ON succeeded. While OFF both preview-ready flags were false; ordinary video returned after ON while Mini2 remained absent. The collector consumed 1.578125 CPU seconds over a 3.0197-second ON sample versus 0.046875 CPU seconds over a 3.0048-second OFF sample. These are short process CPU samples, **not battery-runtime or wattage measurements**. Cameras were restored to ON.

The actual Mini2 power cycle and physical 25-fps recording were not tested because Mini2 and the pump were absent. Capture release does not disconnect USB electrical power; attached sensors can still consume standby power.

## Deployment and source boundaries
Windows UI and `auto_titrator/camera_power.py` match source hashes. Backend changes were applied as a zero-fuzz scoped patch, retaining the pre-existing Windows difference in pump-reset support. AST comparison confirms identical deployed power handler, capture loop, Mini2 opener, CSV-start power gate and stream readiness logic. See `deployment.json`.

No application dependency, extra project copy, release upload, or native APK/EXE rebuild. Runtime/wiki changes already in the workspace are excluded from this commit.
