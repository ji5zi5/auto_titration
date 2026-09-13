# UI demo presentation validation — 2026-09-13

## Scope and cleanup plan
Worker 2 owns index.html, styles.css, DESIGN.md and this validation note. No backend, native Android or hardware command changes.

Before implementation, the existing 12 website asset tests ran: 11 passed, one pre-existing failure was the remote-help forced `<br>`. Plan: retain all DOM IDs and interaction bindings, promote navigation outside drawers, adjust existing layout rules rather than add a parallel theme, enlarge readings, and keep laptop previews side by side. Remove the forced line break while retaining the safety warning. Replace unrelated marketing-design guidance with the instrument contract.

Second, smell-focused pass: reduce ubiquitous 850–950 font weights, consolidate duplicate button/state rules, and keep camera preview height bounded on laptops. Regression evidence from the first pass: all 12 website tests passed; isolated browser checks at 375/768/1024/1440 passed for full and compact modes. Writer/reviewer separation: implementation is worker-2; independent final review belongs to leader/team review lane.

## Evidence
Verification is isolated: Playwright intercepts every network request; static website assets load locally and all service requests receive a fixture 503. No real pump command is sent. Offline placeholders and missing readings are deliberately retained rather than replaced by fabricated experiment data.

Fresh test results, screenshots, and caveats are recorded below after the final pass.

## Final verification
- PASS: `python3 -m unittest tests.test_website_assets tests.test_remote_config -q` — 14 tests, including new permanent navigation/responsive contract. The remote-config test uses an ephemeral loopback fixture, not hardware.
- PASS: `node tests/js/test_remote_control.js`, `test_remote_auto_sync.js`, `test_demo_view.js`, `test_web_request_lifecycle.js` — settings, STOP priority, synchronization, session/results, and request lifecycle regression checks.
- PASS: all 87 current DOM IDs are unique; every original ID from baseline `bee3af0` remains.
- PASS: `node --check website/app.js` and `git diff --check`. No TypeScript configuration or dedicated HTML/CSS linter is present; static asset contracts and actual Chromium CSS/DOM rendering are the available checks.
- PASS: `node /tmp/verify-presentation.cjs` — full/compact, settings-open, and actual result-tab checks at 375/768/1024/1440; no horizontal overflow; laptop cameras share a row; navigation remains visible; compact STOP stays in the viewport after scrolling.
- PASS: `node /tmp/verify-presentation-populated.cjs` — same checks with 768px-high viewports and explicitly labeled synthetic SVG geometry previews, not experiment data.
- Screenshots: `/tmp/ui-demo-worker2/{375,768,1024,1440}-{full,compact,settings,results}.png`; populated counterparts under `/tmp/ui-demo-worker2/populated/`. Logs: `results.log`, `populated-results.log` in the same root.
- Visually inspected: 1440 full, 1024 full, 375 compact, 375 results, and 1024 populated full. Fixed oversized font weights, preview-width shrinkage, and grid image min-size clipping exposed by that inspection.
- Initial tooling attempts used unavailable local Python Playwright and an older cached Node package; final verification uses the existing `/tmp/ui-demo-browser/node_modules/playwright` and installed Chromium. No application dependency was added.

## Remaining integration checks
Worker-1 owns navigation/server-authority JavaScript and the error/load dataset used to suppress broken-preview icons. The presentation hides notebook forms in `remote-controller-mode` and hides images marked `data-stream-state="error"` without collapsing their geometry. Integration must verify those JS/CSS contracts together. Real cameras, physical device safe areas, assistive technology, and actual hardware STOP feedback were not tested.

Subagent skip reason: the inbox initially requested a native test probe, but the leader clarified the active Conductor restriction. The read-only child was interrupted; no child findings or edits were integrated. All implementation and reported verification were executed directly in the Team lane.

## Durable evidence
All 32 final screenshots and test logs are preserved in `docs/ui_demo_validation/presentation/` (synthetic preview variants in `populated/`). Reproduce from repository root with `node docs/ui_demo_validation/verify_presentation.cjs` and `node docs/ui_demo_validation/verify_presentation_populated.cjs`; set `PLAYWRIGHT_MODULE` if the existing tool package lives elsewhere. Scripts write fresh results to /tmp/ui-demo-worker2 and intercept every service request. The populated fixture confirms uncropped, contained imagery after the CSS grid min-size fix.

## Integrated authority rerun — task 5
The initial presentation harness predated the independent remote-role/compact-view split. On the integrated app, a phone's full view correctly remains a remote controller; expecting its notebook forms to become editable was an obsolete test assumption, not a product defect.

Both harnesses now independently expect remote authority when compact is requested or width is at most 700px. They assert both notebook forms remain hidden for remote roles, and that full notebook settings are editable after opening the drawer. Actual result-tab navigation remains checked in phone full view. The local app.js matched the integrated leader app byte-for-byte before this rerun; no product logic was changed.

Fresh PASS: both presentation scripts, all four widths, 32 refreshed screenshots; 375 full settings are remote-readonly, 768/1024/1440 full settings are notebook-editable. Both Node syntax checks and git diff whitespace checks pass. Updated durable screenshots and logs supersede the initial captures. No real hardware access.
