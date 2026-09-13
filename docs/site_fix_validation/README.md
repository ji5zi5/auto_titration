# Windows site fixes — 2026-09-10
Implemented:
- Forward collector HTTP errors with original status/body; transport failures report unknown POST outcome rather than false certainty of disconnection. No POST retry.
- Deduplicate CSV/motion requests while emergency STOP can preempt. Cross-action stale POST responses and older GET/SSE CSV revisions do not overwrite accepted stop state.
- Download at most once per backend/session/start timestamp. Accept direct recording->stopped and preserve genuinely fresh recording after pump-only STOP.
- Withhold final predictions for fewer than8 complete observations, recording span below3s, no positive volume progression, or exact flat sensor data. These are engineering input guards, NOT proof an endpoint has been observed. All final-model/fallback paths pass the same guard; raw feature rows retained.
- UI shows withheld/unavailable reason and clears stale predicted numbers.
- Windows final endpoint path now includes the existing frozen sensor ranker + runtime dependency module + artifact + launcher option. Causal automatic-stop model unchanged; no retraining.
Validation:
- See python-tests.log, js-tests.log, windows-staged-tests.log, native-import.log.
- Original12CSV remain eligible; native Windows and WSL frozen predicted volumes match at6decimal places (model_parity.json).
- Independent review native agent01a08aed-71cb-7f01-915f-1ed2d8cacacb: final APPROVE after staleGET/SSE fix.
Deployment:
- Windows8files listed with hashes/backups in windows-deployment.json.
- Collector reset-endpoint work intentionally excluded.
- No process restart, pump actuation, firmware upload, or new package installation.
- Restart21BAT and reload browser to activate. Firmware unchanged by this site-fix task.
Remaining boundary:
- Windows sklearn1.9 vs artifact-trained1.8 emits InconsistentVersionWarning. Twelve fixed replays match, not a guarantee of all future cross-version behavior.
- Recording >=3s and non-flat data is only eligibility, not independently validated endpoint correctness.
- No live wet run/end-to-end motor test performed.
