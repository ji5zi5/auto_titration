# 적정 종류 조건부 센서 당량점 추정 모델

이 결과는 같은 12회 개발 자료에서 적정 종류별 설정을 선택한 값이며, 독립 검증값은 아니다.

- 사전에 알려진 조건: 적정 종류
- 센서 입력: HSV 3개 채널과 열화상 2개 채널의 시퀀스 변화
- 제외 입력: 미지 시료 농도, 현재 주입량, 이론 당량점, 시간, 진행률, 지시약
- 표준용액 농도: 모든 실험에서 0.100 M로 같아 입력에서 제외

## 결정론적 재실행 확인

| 시드 | MAE (mL) | RMSE (mL) | MAPE (%) |
|---:|---:|---:|---:|
| 42 | 0.077543 | 0.090773 | 0.295000 |
| 1729 | 0.077543 | 0.090773 | 0.295000 |
| 20260728 | 0.077543 | 0.090773 | 0.295000 |

## 한계

- The four type-specific configurations were selected on these same 12 development runs.
- The search compared 2,030,370 configuration combinations (1,006,020 initial plus 1,024,350 dense aggregation settings), so selection optimism is substantial.
- The evaluated run was excluded from ranker fitting but its error participated in final configuration selection.
- The candidate-generation grid was developed in the same research dataset and has no independent preregistration provenance.
- The result is not an independent external-validation estimate.
- Each chemistry/concentration condition has one run, so condition shift and run variation are confounded.
- Training labels use theoretical rather than independently observed endpoints.
- The complete recorded sequence and terminal sensor state are used for endpoint localization.
- The estimated endpoint is not a measured physical stop-volume error.
