PASS

# 최종 검증 판정: 적정 종류 조건부 센서 모델 보강

## 차단 사항

없음. 수치, 누수 감사, 탐색 범위 표기, 재현 산출물, 그래프와 테스트 기록이 서로 일치한다.

## 확인된 결과

- 개발 자료 12회의 MAE는 `0.077543 mL`, RMSE는 `0.090773 mL`, MAPE는 `0.295000%`이다.
- 12회 모두 상대오차 1% 이내이며 최대 절대오차는 `0.156127 mL`이다.
- 최종 평가기, 고정 재현 스크립트와 조밀 집계 탐색의 12개 예측값 및 선택 프레임이 정확히 일치한다.
- 최종 MAPE는 후보 오라클 MAPE와 같다.
- 평가 run은 해당 후보 평가기의 학습과 스케일링에서 제외되었다.
- 현재 주입량, 이론 당량점, 시간, 진행률, 미지 시료 농도와 지시약은 추론 특징에서 제외되었다. 적정 종류만 사전에 알려지는 라우팅 조건으로 사용했다.
- 표준용액 농도는 1,822개 행에서 모두 `0.100 M`로 같아 입력에서 제외했다.
- 세 지정 숫자에서 같은 결과가 나온 사실은 seed 강건성이 아니라 결정론적 반복 확인으로만 기록했다.
- 입력 CSV 12개와 관련 스크립트의 SHA-256 해시, 재현 산출물 해시와 조밀 탐색 감사 폴더의 `SHA256SUMS`가 모두 일치했다.
- 관련 분석 전체 41개 테스트가 통과했고, 최종 수정 뒤 핵심 회귀시험 9개도 다시 통과했다.
- 그래프 4개는 모두 가로 1,800 px 이상, 약 300 dpi이며 원자료 CSV를 함께 보존했다.

## 해석 범위

이 결과는 초기 1,006,020개와 조밀 집계 1,024,350개를 합친 총 2,030,370개 설정을 같은 12회 개발 자료에서 비교해 고른 값이다. 평가 run의 정답은 최종 설정 선택에 사용되었고 후보 생성 격자도 같은 자료에서 개발했다. 따라서 `0.295000%`는 새 시료의 독립 검증 정확도가 아니라 개발 자료 내부의 사후 선택 결과이다. 또한 기록이 끝난 전체 센서 시계열에서 당량점 위치를 찾은 값이므로 실제 자동 정지 부피 오차와 구분한다.

## 근거

- `data/ml/type_conditioned_sensor_sequence_search/summary.json`
- `data/ml/dense_type_conditioned_sensor_ranker_reproduction/final_summary.json`
- `docs/report_evidence_no_new_wet/model_search_audit/dense_aggregation_search/`
- `docs/report_evidence_no_new_wet/type_conditioned_ml_full_tests.log`
- `docs/report_evidence_no_new_wet/type_conditioned_ml_targeted_recheck.log`
- `docs/report_evidence_no_new_wet/적정종류_조건부_모델_추가결과.md`
- `docs/report_evidence_no_new_wet/보고서_교체문안.md`
