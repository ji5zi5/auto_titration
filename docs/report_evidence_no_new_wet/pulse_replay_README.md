# 펄스 정책 오프라인 재생 분석

`tools/pulse_replay_analysis.py`는 기존 12회 CSV의 시간순 `endpoint` 판정 라벨을
그대로 재생하여 다음 세 정지 스케줄을 비교한다.

1. `continuous_immediate_stop`: 첫 endpoint 양성 행에서 즉시 정지
2. `continuous_0.4s_confirmed_stop`: endpoint 양성이 0.4초 연속된 첫 행에서 정지
3. `step5_0.5s_mixed_wait`: 첫 양성에서 연속 주입을 멈춘 것으로 간주하고, 0.5초마다
   `STEP 5`의 명목 부피를 더하면서 0.4초 연속 양성을 확인

## 실행

저장소 루트에서 기존 inventory의 12개 run을 재생한다.

```bash
python3 tools/pulse_replay_analysis.py
python3 tools/pulse_replay_analysis.py --json --output /tmp/pulse-replay.json
python3 tools/pulse_replay_analysis.py --json --output data/analysis/report_evidence_no_new_wet/pulse_replay_simulation.json
python3 -m unittest tests.test_pulse_replay_analysis -v
```

임의 CSV도 지정할 수 있다.

```bash
python3 tools/pulse_replay_analysis.py --json path/to/run.csv
```

시간, 주입 부피, endpoint 불리언 또는 상태 라벨 컬럼은 대소문자·공백·괄호·단위
표기의 흔한 변형을 정규화하여 찾는다. 필수 컬럼 누락, 비수치 값, 비단조 시간/부피,
endpoint 양성 행 부재는 진단으로 남긴다. 입력 SHA-256과 실제 선택된 컬럼명도 JSON에
기록하므로 같은 입력과 옵션으로 결과를 재현할 수 있다.

## 해석 제한

이 결과는 **실제 습식 성능이 아니라 기존 라벨의 반사실적 모의 계산**이다. 기존 CSV는
가상 정지 뒤의 혼합, 센서 안정화, 펌프 관성, 실제 `STEP 5` 토출량을 기록하지 않았다.
따라서 혼합대기 정책에서도 이후 endpoint 라벨의 시각은 원래 연속 주입 실험의 시각을
그대로 사용하며, `simulated_stop_volume_ml`은 `ml_per_step` 설정으로 계산한 명목 명령
부피일 뿐 실측 토출량이 아니다. 정책 간 수치는 정확도 향상, 반복성, 펌프 검증 또는
실험적 우월성의 근거로 사용할 수 없다.

현재 inventory의 12개 CSV 중 endpoint 양성 라벨이 없는 run은 도구가 임의로 보간하거나
성공 처리하지 않고 `no endpoint-positive rows`로 명시한다. 이 경우 synthetic 단위테스트가
정책 계산 자체의 결정성과 경계 동작을 검증하지만, 누락된 습식 근거를 대체하지 않는다.

현재 저장 결과에서는 12개 run을 모두 불러왔고 10개가 정책 계산에 사용 가능했다. 0.4초
연속 양성 정책과 가상 `STEP 5` 정책이 정지한 run은 각각 1개였다. 이는 성공률이 아니라
기존 라벨이 새 지속 조건을 충족하는지 확인한 자료 적합성 결과이다.
