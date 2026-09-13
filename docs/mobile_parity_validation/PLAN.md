# Android 기능 연결 작업

범위: 기존 Android 앱에 Windows의 핵심 수집·예측·펌프 제어 흐름을 연결한다. 소스/실험 원자료/기존 모델을 보존하고 모델 재학습이나 근사 온도 변환은 하지 않는다. 공식 바이너리를 포함한 debug/private-lab APK만 빌드하며 공개 배포하지 않는다.

1. 기존 모델을 휴대폰에서 실행 가능한 데이터로 내보내고, 기존 Python 예측과 수치 일치 시험.
2. 블루투스 전체 명령/ACK와 기본 OFF 자동정지·미세 주입, 최대 시간·부피·비상정지 연결.
3. 공식 온도 경로와 검증 게이트 조사, 측정 범위/시각 출처를 유지한 기록 연결. 미검증 행렬을 정상 섭씨로 표시하지 않음.
4. 농도·pH·상수 조회를 로컬 계산으로 연결. 참 농도/이론부피를 예측 입력으로 대체하지 않음.
5. 기록 종료 후 비동기 분석, CSV·UI에 결과/보류 이유 표시. 대기·정지 중 누적 부피 증가 방지.
6. 대상 테스트, Android debug 빌드 및 패키지 검사. 실제 폰/펌프 시험은 가능한 장치가 있을 때 별도 안전 범위에서 수행.

담당: leader=MainActivity/bridge/session/data/UI 통합과 최종검증; 병렬 bounded executor=모델, 펌프, 화학; thermal explore=공식 경로 read-only 조사.
완료 판정은 실제 테스트/산출물 기준이며, 하드웨어 미검증·미구현 항목은 결과에 명시한다. 캐시 재생성 용량을 확인하고 APK 복사본은 늘리지 않는다.

## First delivery status

Completed: frozen final model export/portable worker, native result/session/CSV integration, p95 parity, debug build, unit/lint/package verification. Initial native subagent handles were not available after turn interruption; no completion claim relies on those absent agents. Final delivered implementation and tests were executed in the leader lane.

Not complete: causal automatic pump control, fully calibrated live matrix path, complete offline chemistry and full sensor synchronization. These are not hidden behind success flags in the first APK. No physical motor commands were issued during implementation.
