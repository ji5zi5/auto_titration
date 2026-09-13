---
title: "detail-windows-handoff-01-part-3"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:54.826Z
updated: 2026-09-10T11:13:54.826Z
sources: []
links: ["detail-windows-handoff-01-part-2.md", "detail-windows-handoff-01-part-3.md", "detail-windows-handoff-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-windows-handoff-01-part-3

원문 [docs/WINDOWS_CODEX_HANDOFF.md](../docs/WINDOWS_CODEX_HANDOFF.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-windows-handoff-01]] / [[detail-windows-handoff-01-part-2]] / [[detail-windows-handoff-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
data/mini2_multi_image_formula/formula_sweep/formula_sweep_report.md
```

해석:

- 같은 이미지 안에서는 raw 값과 CSV 온도가 lookup으로 0 오차 대응될 수 있었다.
- 여러 이미지 전체로 보면 같은 raw 값이 다른 온도를 가질 수 있어 전역 `T=f(raw)` 식은 반증되었다.
- `metadata_u16[284]`를 이용한 후보식은 오차가 작았지만 공식 SDK 복원은 아니므로 본경로로 쓰지 않는다.

### 폐기 또는 본경로 아님

```text
raw_u16 단순 /1024
raw_u16 단순 /8192
raw_u16 /64
전역 선형식 T = a*raw+b
min/max-only scaling
palette/fake-color RGB 분석
<!-- END SOURCE EXCERPT -->

