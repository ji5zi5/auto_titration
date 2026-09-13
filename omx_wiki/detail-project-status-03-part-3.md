---
title: "detail-project-status-03-part-3"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:13:57.378Z
updated: 2026-09-10T11:13:57.378Z
sources: []
links: ["detail-project-status-03-part-2.md", "detail-project-status-03-part-3.md", "detail-project-status-03.md", "detailed-library.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-03-part-3

원문 [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md). 역사 자료 스냅샷: 작성 시점의 주장으로 읽는다.
[[detailed-library]]

분할 이어읽기: [[detail-project-status-03]] / [[detail-project-status-03-part-2]] / [[detail-project-status-03-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
7. 모델 artifact 재생성 절차 문서화

현재 문서상 누수로 보면 안 되는 값:

- 현재 주입량
- 펌프 작동 시간
- 센서값
- 물질 종류
- 표준용액 정보

현재 넣으면 안 되는 값:

- 이론 당량점 부피
- 당량점까지 남은 거리
- 정답 zone label
- 최종 총 주입량
- 전체 진행률
- run duration을 알 때만 계산되는 progress fraction
- row index 기반으로 정답 위치를 추측할 수 있는 값

## 4.8 P1 - 농도 계산 UI 정리

최근 사용자가 지적한 부분이다. 농도 계산창이 이론값을 그대로 보여주면 안 되고, 예측값 기반 계산인지 분명해야 한다.

수정할 점:

1. “이론 pH”와 “예측 pH”를 구분한다.
2. 사용자가 입력한 미지 농도는 모델 예측 농도 계산의 정답처럼 쓰지 않는다.
3. 예측 당량점 부피로 미지 농도를 역산한다.
4. 표준용액 농도, 시료 부피, 반응 가수, 예측 당량점 부피가 계산에 쓰인다는 것을 UI에 짧게 표시한다.
5. 계산 실패 시 `-`만 띄우지 말고 이유를 표시한다.
   - 예: 예측값 없음
   - 예: 농도/부피 입력 부족
   - 예: 모델 로드 실패

## 4.9 P1 - Windows release ZIP 정리

<!-- END SOURCE EXCERPT -->

