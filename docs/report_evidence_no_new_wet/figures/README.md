# 적정 종류 조건부 모델 보고서 그림

## 재생성

```bash
python3 tools/type_conditioned_sensor_sequence_search.py
python3 tools/make_type_conditioned_ml_figures.py
```

그림은 `data/ml/type_conditioned_sensor_sequence_search/summary.json`과
`outer_predictions.csv`에서 생성한다. 실행 중 3개 seed의 12개 예측이 같은지,
예측 CSV에서 다시 계산한 MAPE가 요약 JSON과 일치하는지 확인한다.

## 파일

- `01_actual_vs_predicted.png`: 기준 당량점과 모델 추정값
- `02_ape_by_condition.png`: 12개 조건별 절대백분율오차
- `03_mape_by_titration_type.png`: 적정 종류별 MAPE
- `04_mape_by_method.png`: 비머신러닝·기존 머신러닝·조건부 모델 비교
- `source_data/`: 각 그림의 원본 수치

모든 PNG는 300 dpi이며 가로 1,800 px 이상이다. 새 조건부 모델의 0.30%는
같은 12개 개발 자료에서 2,030,370개 설정을 비교해 선택한 결과이므로 독립 검증값으로
표현하지 않는다.
