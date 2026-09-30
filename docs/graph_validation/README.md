# Result graph verification — 2026-09-15

Synthetic measurements only, not an actual titration result. All browser requests were intercepted; no physical collector, camera, recording, or pump command was used.

## Reproduced defect and repair

`build_live_payload` omitted `csv_session_id`, so `demo-view.appendSample` rejected every actual-shaped SSE sample. Previous handcrafted browser/unit fixtures supplied this missing property and concealed the defect.

- Before: 81 serialized collector frames -> 0 graph samples; no colored trace pixels.
- After: 81 frames -> 81 retained samples at 0–20 seconds, both visible color and trusted Celsius traces painted, results remained visible after finalization/stop, no automatic download.
- Chromium coverage: notebook 1024 px, phone full view 390 px, and legacy collector payload without a session ID. Legacy matching requires a known session and exactly matching start timestamp; unidentified/stale frames remain rejected.
- The backend now emits `csv_session_id`. The frontend compatibility fix is deployed to the Windows loose assets, with all four graph assets byte-equal to the tested files. Backend source is patched for next startup; the running collector was not restarted.

## Reproduce

```sh
python3 -m unittest tests.test_windows_live_collect tests.test_website_assets tests.test_view_navigation tests.test_remote_config -q
node tests/js/test_graph_collector_contract.js
# Uses a separately installed Playwright test tool, not an application dependency.
PLAYWRIGHT_MODULE=/path/to/playwright node docs/ui_demo_validation/verify_graphs.cjs
```

Python regression run: 216 tests, OK (1 skipped). All 14 Node test scripts passed. Chromium checks assert actual canvas trace pixels, sample timestamps, sample retention, result visibility, no runtime errors and no automatic download. See before.json, after.json and results-synthetic.png.

## Limits

No physical chemical experiment was performed. Temperature plotting still requires validated Celsius metadata. Graphs retain the latest 1,500 received samples (about 60 seconds at 25 fps) in browser memory, not a reconstruction of the complete saved CSV; reloading or navigating to a new page loses that page's earlier samples. Reload/session-reset behavior is unchanged; the capacity update is documented below.


## One-minute retention update

The default graph buffer is now 1,500 samples, shared by the app and demo module.
A 25 fps synthetic run retained all 1,500 points from 0.00 to 59.96 seconds through stop.
The unit regression also checks that the next sample at 60 seconds evicts only the oldest point and retains the bound, and that session reset retains the new capacity.

```sh
GRAPH_FRAME_COUNT=1500 GRAPH_FPS=25 OUTPUT=/tmp/graph-minute-validation node docs/ui_demo_validation/verify_graphs.cjs
```

This changes only browser graph retention, not recording FPS, CSV rows, or pump control. At lower received sample rates, the time span is longer than one minute; retention is sample-count-based.
