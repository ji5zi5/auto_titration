---
title: "detail-site-validation-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:14.245Z
updated: 2026-09-10T11:10:14.245Z
sources: []
links: ["detail-site-validation-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-site-validation-01

## 문서의 역할과 해석
사이트 수정 시점의 검증 기록. 현재 하드웨어 재시험 결과 아님.

원문: [docs/site_fix_validation/README.md](../docs/site_fix_validation/README.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-site-validation-01]]

<!-- BEGIN SOURCE EXCERPT -->
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
<!-- END SOURCE EXCERPT -->

