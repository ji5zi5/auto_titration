---
title: "detail-ml-detailed-01-part-3"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:59.316Z
updated: 2026-09-10T11:13:59.316Z
sources: []
links: ["detail-ml-detailed-01-part-2.md", "detail-ml-detailed-01-part-3.md", "detail-ml-detailed-01.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-ml-detailed-01-part-3

원문 [docs/ml_equivalence_result_detailed_summary.md](../docs/ml_equivalence_result_detailed_summary.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-ml-detailed-01]] / [[detail-ml-detailed-01-part-2]] / [[detail-ml-detailed-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
약산/약염기 계열은 반응 곡선이 강산-강염기처럼 급격하지 않을 수 있다. 또한 지시약 색 변화와 실제 당량점이 완전히 같은 지점이라고 보기 어렵고, 열 변화도 조건에 따라 완만할 수 있다.

현재 모델은 색/열 곡선에서 변화가 큰 후보를 뽑고 그 후보 중 하나를 고르는 방식이다. 만약 색 변화와 열 변화가 당량점보다 앞이나 뒤에서 더 뚜렷하게 나타나면 모델이 잘못된 후보를 고를 수 있다.

### 10.3 feature를 많이 넣는다고 좋아지지는 않았다

`fusion_expanded`, `thermal_expanded`, `color_expanded`처럼 feature를 많이 늘린 모델이 항상 좋아지지는 않았다. 오히려 현재 12개 run에서는 잡음이나 과적합이 생길 가능성이 있다.

즉, 현재 데이터 크기에서는 복잡한 모델보다 compact한 색+열 융합 후보 방식이 더 안정적이었다.

### 10.4 주입량 정보는 중요하다

`compact_plus_no_progress`처럼 주입량/진행 정보를 제거한 모델은 성능이 크게 나빠졌다. 이것은 센서값만으로는 후보를 안정적으로 고르기 어렵다는 뜻이다.

하지만 주입량은 정답 누수가 아니다. 실제 장치에서는 펌프 시작 시간, 유량 보정값, 녹화 시간으로 현재 주입량을 계산할 수 있다. 따라서 최종 장치 설명은 다음처럼 해야 한다.

```text
색상 센서 + 열화상 센서 + 주입량 정보를 융합하여 당량점 후보를 예측했다.
```

“센서만으로 당량점을 정확히 맞혔다”라고 하면 부정확하다.

<!-- END SOURCE EXCERPT -->

