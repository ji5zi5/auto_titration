---
title: "detail-auto-stop-02"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:15.191Z
updated: 2026-09-10T11:10:15.191Z
sources: []
links: ["detail-auto-stop-01.md", "detail-auto-stop-02.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-auto-stop-02

## 문서의 역할과 해석
건식 제어 시험·미세 주입·안전성 및 습식 검증 공백.

원문: [docs/AUTO_STOP_VALIDATION.md](../docs/AUTO_STOP_VALIDATION.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-auto-stop-01]] / [[detail-auto-stop-02]]

<!-- BEGIN SOURCE EXCERPT -->
- 자동 판정 콜백과 사용자의 녹화 종료·펌프 후퇴가 동시에 실행될 때는 물리 정지를 먼저 요청하고 자동정지 판정을 해제한 뒤 CSV 전환 잠금을 획득한다. 각 정지 경로에는 별도 소유 토큰을 부여하고, 지연된 센서 큐 정리를 위한 정지 래치는 해당 CSV 세션 번호가 일치할 때만 해제한다. 따라서 자동 경로가 먼저 끝나도 수동 경로가 남아 있으면 정지 의도가 유지되고, 이전 세션의 늦은 콜백이 새 세션의 종료 래치를 지울 수 없다. 자동 콜백이 판정 잠금을 보유한 채 CSV 전환을 기다리는 상황과 한 경로가 먼저 CSV를 닫는 상황을 의도적으로 만든 회귀시험에서도 교착·중간 재시작 없이 종료됨을 확인하였다.
- 자동정지 하드웨어 경로는 정답·이론 당량점·진행률·미지 시료 농도 입력이 포함된 모델을 거부하고, 선택한 적정 종류에 해당하는 모델과 유효한 센서 특징이 모두 있어야 동작한다. 표준용액 농도와 현재 명령 주입량은 실험 중 알 수 있는 값이므로 허용한다.
- 자동 펌프 시작 뒤 필수 센서·색상·모델 계산이 실패하면 최대 부피까지 계속 돌지 않고 즉시 정지 요청과 기록 종료를 수행한다. 최신 프레임만 남기는 분석 대기열에서도 한 번 발생한 필수 입력 오류는 정상 후속 프레임이 덮어쓸 수 없도록 세션별 실패 상태로 고정한다.
- 연속 구간과 펄스 구간 모두 명목 유량과 별도의 최대 유량 상한으로 계산한 보수적 누적 부피를 사용한다. 최대 유량 상한이나 펄스당 부피 상한이 없으면 자동 펌프를 시작하지 않는다.

## 검증 범위와 한계

펌웨어 계약, 펄스 상태 전환, 시리얼 명령 확인, 주입량 기록과 자동 정지 연동은 하드웨어 없는 단위·통합시험으로 확인하였다. 기존 12회 습식 적정은 사람이 정지한 자료이므로 새 미세 주입 기능의 정밀도 근거가 아니다.

2026-08-06에 펌웨어를 Arduino UNO 대상으로 실제 컴파일하고, 핵심 정지·펌웨어·Windows 서버 회귀시험 210개와 펄스 제어·실시간 모델·웹 UI를 포함한 관련 회귀시험 245개를 다시 실행하였다. 캐시 파일을 제외한 깨끗한 환경에서 전체 저장소 회귀시험 1,185개도 통과하였다. 최신 펌웨어의 Arduino Uno 컴파일 결과는 프로그램 저장공간 4,174 byte, 전역 변수 443 byte였으며 오류가 없었다.

```bash
arduino-cli compile --fqbn arduino:avr:uno auto_titrator/arduino_stepper --warnings all
.venv/bin/python -m unittest -v tests.test_auto_stop tests.test_pulse_control tests.test_typewise_live_model tests.test_windows_live_collect tests.test_website_assets tests.test_arduino_firmware
```

기존 12개 CSV에는 새 펄스 제어가 적용되지 않았으므로 `tools/pulse_replay_analysis.py`로 반사실적 재생만 별도 수행하였다. 12회 모두 불러왔고 endpoint 양성 행이 있던 10회 중 0.4초 연속 양성 조건과 가상 `STEP 5` 정책으로 정지할 수 있었던 자료는 1회뿐이었다. 이 결과는 현재 라벨의 지속성이 제한적임을 보여 줄 뿐 실제 자동정지 성능이나 펄스 제어의 개선 효과를 증명하지 않는다. 재현 가능한 전체 결과는 `data/analysis/report_evidence_no_new_wet/pulse_replay_simulation.json`에 저장하였다.

후속 물 보정은 다음 양식과 명령으로 기록할 수 있다.

```text
docs/report_evidence_no_new_wet/pump_position_calibration_template.csv
.venv/bin/python tools/pump_calibration.py --write-position-template docs/report_evidence_no_new_wet/pump_position_calibration_template.csv
.venv/bin/python tools/pump_calibration.py --input-csv <측정완료CSV> --nominal-ml-per-step 0.0099 --output data/raw/pump-position-analysis.csv --summary-output data/raw/pump-position-analysis.summary.json
```

양식 생성 기본값과 허용 최솟값은 위치·명령 조합당 10회이다. 더 많이 반복하려면 `--template-repeats <10 이상>`을 지정한다.

따라서 보고서에서는 이 기능을 **소프트웨어 구현 및 건식 시험 완료**로만 표현한다. 실제 장치에서 5스텝이 0.0495 mL를 토출하는지, 한 방울에 해당하는지, 정지 지연과 과주입량이 얼마나 줄었는지는 습식 반복시험 전에는 주장하지 않는다.
<!-- END SOURCE EXCERPT -->

