---
title: "detail-project-status-03"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:13.292Z
updated: 2026-09-10T11:10:13.292Z
sources: []
links: ["detail-project-status-01.md", "detail-project-status-02.md", "detail-project-status-03-part-2.md", "detail-project-status-03-part-3.md", "detail-project-status-03.md", "detail-project-status-04.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-03

## 문서의 역할과 해석
통합 현황 원문. 작성시점이 다른 단락과 완료/미완료 표현을 구별.

원문: [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-project-status-01]] / [[detail-project-status-02]] / [[detail-project-status-03]] / [[detail-project-status-04]]


분할 이어읽기: [[detail-project-status-03]] / [[detail-project-status-03-part-2]] / [[detail-project-status-03-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
docs/mobile_companion_runbook.md
docs/hikmicro_apk_androguard_summary.txt
docs/ml_current_volume_no_progress.md
docs/report_laptop_app_development_draft.md
docs/science_fair_report_final_draft.md
docs/보고서.txt
docs/포스터_문장_정리.txt
docs/포스터_연구요약_앱개발_간략문장.txt
docs/포스터_windows_android앱개발_문장.txt
docs/포스터_머신러닝_모델선정.txt
docs/포스터_적정종류별_성능표.csv
docs/포스터_적정종류별_성능표.txt
docs/포스터_그래프1_데이터수집_설명.txt
docs/포스터_결론_기대효과.txt
```

포스터/보고서 문장 작업에서 정리된 방향은 다음과 같다.

- 너무 AI 문체처럼 길게 쓰지 않는다.
- 포스터 문장은 한두 문장 또는 짧은 개조식으로 쓴다.
- “구성하였다”보다 실제 만든 기능이 드러나게 쓴다.
- 중화적정에서 뷰렛 콕 조절의 불편함과 인적 오류를 동기로 둔다.
- 종말점과 당량점 차이를 명확히 설명한다.
- 카메라 모델명보다 색 변화, 온도 변화, 주입량, 농도 계산 기능을 중심으로 설명한다.
- 포스터 성능 수치는 개발셋 기준임을 숨기지 않는다.

## 4. 앞으로 수정해야 할 점 전체 목록

아래는 실제로 이어서 수정하거나 확인해야 하는 작업 목록이다.

## 4.1 P0 - Windows 실험 본경로 검증

가장 먼저 해야 한다. Android나 새 기능보다 실제 전람회 실험 데이터 수집이 우선이다.

수정/확인할 점:

1. Windows에서 `21_open_dashboard_server.bat` 실행 확인
   - 서버가 8765 포트로 뜨는지 확인
   - collector가 8766 포트로 뜨는지 확인
   - 수집기 포트 닫힘 메시지가 있으면 collector 프로세스가 죽었는지 확인

2. Arduino 재연결 흐름 확인
   - 서버를 먼저 켠 뒤 Arduino를 나중에 꽂아도 잡히는지 확인
   - Arduino IDE Serial Monitor가 열려 있으면 포트를 못 잡으므로 이 경우 UI에 명확히 표시되게 개선
   - 재시도 로그가 너무 조용하면 “펌프 검색 중” 같은 상태 표시 추가

3. 녹화 시작/펌프 시작 동시성 확인
   - 녹화 시작 시 `b` 명령이 실제로 전송되는지 확인
   - 녹화 종료 시 `c` 명령이 실제로 전송되는지 확인
   - 후퇴 버튼이 `a`를 보내는지 확인
   - 펌프가 연결 안 되어도 CSV 녹화 자체는 막히지 않게 유지

4. CSV row 수 확인
   - 10초 녹화에서 기대 row 수가 너무 적지 않은지 확인
   - 일반 카메라/열화상 FPS와 CSV row 기록 주기가 실제로 맞는지 확인
   - row 수가 적으면 ML 학습용으로 가치가 떨어지므로 먼저 고쳐야 함

5. Mini2와 일반 카메라 동시 표시 확인
   - 일반 카메라가 바로 표시되는지 확인
   - Mini2 raw frame이 바로 표시되는지 확인
   - 열화상 ROI 온도값이 `-`로 남지 않는지 확인
   - Mini2가 없을 때에도 일반 카메라와 CSV 녹화가 동작하는지 확인

6. ROI 실험 흐름 단순화
   - 자동 ROI가 불안정하면 수동 사각형 ROI를 기본값으로 둔다
   - 일반 카메라 ROI와 열화상 ROI를 따로 잡게 한다
   - 실험 직전 ROI lock 상태가 명확히 보이게 한다

## 4.2 P0 - live 머신러닝 예측 연결 확인

현재 이론값이 예측값처럼 보이면 안 된다. live 앱은 typewise classifier 결과를 우선 사용해야 한다.

수정/확인할 점:

1. 녹화 종료 후 CSV에서 다음 열 확인

```text
predicted_equivalence_volume_ml
predicted_equivalence_source
predicted_sample_concentration_M
predicted_ph
```

2. `predicted_equivalence_source`가 다음인지 확인

```text
typewise_frame_zone_classifier
```

3. 웹 UI 표시가 다음으로 나오는지 확인

```text
적정 종류별 분류 모델
```

4. 예측값이 이론 당량점과 항상 같게 고정되는지 확인
   - 항상 같으면 모델 예측이 아니라 이론값 fallback일 가능성이 크다.
   - `data/labeled/typewise-current-volume-classifier.pkl` 로드 실패 여부를 확인한다.

5. 농도 계산창의 기준 정리
   - 미지 시료 농도 입력값은 정답 계산에 쓰면 안 된다.
   - 예측 당량점 부피로 농도를 역산해야 한다.
   - 웹 UI 문구는 “예측 pH”처럼 표시한다.

6. 성능 표현 수정
   - `MAPE 1.27%`는 개발셋 12개 run 기준이다.
   - 새 독립 실험 성능으로 표현하지 않는다.
   - 포스터에는 “개발셋 기준” 또는 “수집 데이터 기준”으로 표현한다.

## 4.3 P0 - Android 앱 수정점

사용자가 Windows 환경에서 이어서 작업하려는 핵심 중 하나다. Android는 “완성본”이 아니라 “수정해야 할 대상”이다. 현재 Android 계획의 1순위는 앱 UI나 CSV가 아니라 공식 HIKMICRO 앱의 Mini2 호출 경로를 찾아 우리 앱에서 최소 재현하는 것이다.

P0 수정 목표:

```text
공식앱이 Mini2를 여는 정확한 순서를 찾는다.
그 순서를 우리 Android 코드에서 최소 구현한다.
실제 Mini2 frame callback이 들어오는지 확인한다.
frame shape와 온도 변환을 공식 앱/Windows DLL 결과와 비교한다.
```

P0 작업 순서:

<!-- END SOURCE EXCERPT -->

