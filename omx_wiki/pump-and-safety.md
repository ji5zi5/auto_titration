---
title: "Pump and Safety"
tags: ["펌프", "Arduino", "STEP", "자동정지", "유량"]
created: 2026-09-10T11:05:02.754Z
updated: 2026-09-10T11:05:02.754Z
sources: []
links: ["consultation-and-report.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Pump and Safety

# 펌프와 안전 제어
## 기구와 유량
100 mL 주사기, 내경 약 35 mm, 스텝각 1.8도(200 step/rev), 리드 2 mm/rev. HIGH/LOW 각각 5000 μs이면 명목 100 step/s이며 이론 유량 약 0.962 mL/s.
사용자가 10 mL 토출 시간을 확인해 운용 설정 약 0.99 mL/s를 사용했다. 반복 원자료가 없으므로 실제 반복정밀도·피스톤 위치별 유량 검증은 안 됐다. 2.9% 차이는 이론값과 설정값 차이이지 측정 오차가 아니다.
공기 압축·기포·마찰 문제가 있었고 사용자는 방향 변경 후 토출이 개선됐다고 보고했다. 이것만으로 물리 유량 일정성을 증명하지 않는다.

## 명령과 파일
auto_titrator/arduino_stepper/arduino_stepper.ino 및 command_parser.h.
현재 문서 기준 a=후퇴, b=주입, c=정지. 과거 방향이 변경됐으므로 배선·방향을 실물 확인해야 한다. D2 STEP, D3 DIR, D4 ENABLE, 9600 baud가 원본 기준.
최신 보강은 G <ms> 안전기한, STEP 1~200, 수락·완료 ACK. 원본 a/b/c만 있는 펌웨어는 새 펄스·ACK 기능을 지원하지 않는다. 펌웨어 업데이트 필요성을 빠뜨리지 않는다.

## 선택형 자동정지 및 펄스
기준색 약 1초와 실시간 모델을 정지 상태에서 준비. 접근 점수 0.20에서 연속 주입 정지, 0.50초 대기, STEP 5 수락·완료 확인 후 다시 0.50초 대기·판정. 지속 색 변화 0.4초 조건 등이 사용된다.
명목 STEP 5 = 0.99/100×5 = 0.0495 mL. 실제 한 방울 부피는 미측정.
필수 센서 오류 고정, 최대 시간/누적 부피, 비상정지 우선, 방향 쓰기와 취소의 직렬화, 중복 시작 및 이전 세션 콜백 차단. 불확실한 펄스는 재전송하지 않는다.
구현: auto_titrator/auto_stop.py, auto_titrator/pulse_control.py, tools/windows_live_collect.py.

## 검증 및 후속
docs/AUTO_STOP_VALIDATION.md에 과거 핵심 210개·전체 1,185개 시험 통과 및 UNO 4,174 byte/전역 443 byte 컴파일 기록. 이번 위키 작성에서 재실행한 것은 아니다.
기존 12회는 사람이 정지. CSV 가상 재생에서 양성 자료 10회 중 지속 조건 정지는 1회로, 실제 자동정지 성능 증거가 아니다.
tools/pump_calibration.py와 pump_position_calibration_template.csv는 초기/중간/말기 × STEP5/10/20/50 반복 측정 분석 도구다. 빈 양식은 결과가 아니다.
관련: [[consultation-and-report]].

