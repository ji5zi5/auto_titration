# Controls/defaults/results update

ROI delete added to the first control group; automatic ROI moved into experiment settings. Pump dispense/retract/stop share one second row (including phone compact). Results omit the live status/volume/time panel; final result figures remain. Defaults: strong acid/strong base, hydrochloric acid sample, sodium hydroxide standard,0.100 M fields and20.00mL sample volume; matching hidden theory reference20.00mL. No ML or concentration formulas changed.

Delete uses the existing collector /api/roi-unlock reset:true, including already-unlocked setup state. Auto ROI is stopped before deletion; recording and in-flight/queued automatic requests prevent deletion. Collector rejection preserves local regions. Unsupported native APK reset remains hidden. Existing Windows collector reset endpoint confirmed; no backend restart needed.

Observed automatic ROI capability: current collector reports yolo_enabled=true and yolo_available=true, continuous tracking off. On-demand candidate endpoint and missing-model/available-model unit tests verified. Actual live beaker detection success was NOT tested or claimed; no live ROI mutation was sent.

Verification:16 Python website/navigation tests,12 Node suites,3 targeted collector ROI/YOLO tests,4-width mocked Chromium navigation/defaults/row placement/results visibility/actual reset click/native hide and populated-preview checks pass. Mocked ROI reset asserts reset:true, both regions cleared and no pump/recording action. Screenshots are fixtures, not experimental measurements. All3Windows web hashes match; other top-level website assets unchanged. No APK/EXE rebuild, real hardware commands, server restart or push.

This note supersedes earlier default chemistry, standalone STOP, top-level auto ROI and result-stage presentation notes. Browser summary controlCommands refers to navigation; the explicit user-click ROI reset is separately tested with intercepted requests.

Latest placement correction: automatic ROI now sits beside manual ROI selection, deletion and locking, not inside settings. All pump actions remain in the second group. Four-width browser checks and16Python tests pass. A regression also prevents a late ROI setup callback from enabling deletion after recording has started. Windows3asset hashes refreshed.

Latest user placement: automatic ROI moved to the last slot of the first row; collection toolbar CSV download removed, result CSV download retained. Legacy optional link lookup stays null-safe. Python16 and mocked Chromium4-width checks pass, including no download in controls and visible download in results. Windows index/styles copied and hash verified.
