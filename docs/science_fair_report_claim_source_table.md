# 자동적정기 보고서 Claim-Source Table

작성일: 2026-06-02

이 표는 최종 보고서에 들어갈 주요 주장과 수치가 어디에서 나온 것인지 추적하기 위한 근거표이다. 최종 원고 작성 시 본문에는 내부 파일명을 길게 노출하지 않고, 필요한 경우 “실험 CSV 분석 결과”, “앱 구현 기록”, “펌프 보정 기록”처럼 자연스럽게 풀어 쓴다.

| 보고서 주장/내용 | 사용할 표현 | 근거 자료 | 주의사항 |
|---|---|---|---|
| 수동 적정은 색 변화 판단, 시간 기록, 주입량 기록이 사람마다 달라질 수 있다. | 연구 동기에서 수동 적정의 한계로 설명 | PDF 추출 p.4 부근 `/tmp/auto_titration_pdf_extract.txt`:26, `docs/report_laptop_app_development_draft.md`:5 | “완벽히 해결” 같은 표현 금지 |
| 당량점과 종말점은 다르며 지시약 변색 범위 때문에 차이가 생길 수 있다. | 이론 배경의 핵심 개념으로 설명 | PDF 추출 p.5 부근 `/tmp/auto_titration_pdf_extract.txt`:30, `docs/report_laptop_app_development_draft.md`:11-21 | 종말점 자동 인식만으로 당량점 확정이라고 쓰지 않기 |
| 농도 계산은 당량 관계 `Cs Vs ns = Ct Vt nt`를 사용한다. | 농도 계산식과 미지 농도 역산식 제시 | `docs/report_laptop_app_development_draft.md`:13, `auto_titrator/chemistry.py`:130-206 | 식의 변수 정의를 반드시 같이 적기 |
| pH 곡선은 실측 pH가 아니라 농도·해리상수 기반 이론 곡선이다. | 이론 pH 곡선 계산 기능으로 설명 | `docs/report_laptop_app_development_draft.md`:15-19, `auto_titrator/chemistry.py`:317-406 | 실제 pH 센서 측정값처럼 쓰지 않기 |
| 지시약 변색 범위는 페놀프탈레인 pH 8.2~10.0, 메틸오렌지 pH 3.1~4.4, BTB pH 6.0~7.6으로 저장하였다. | 이론 pH와 지시약 선택의 연결 기준으로 설명 | `docs/report_laptop_app_development_draft.md`:21 | “색이 변하면 무조건 당량점” 금지 |
| 시린지 펌프는 스테퍼 모터, T8 리드스크류, A4988, 아두이노로 구성하였다. | 장치 제작 섹션에 기술 | PDF 추출 p.6~p.10 부근 `/tmp/auto_titration_pdf_extract.txt`:34, 55-60; `docs/report_laptop_app_development_draft.md`:23 | 제작 세부는 30쪽 제한 때문에 핵심만 |
| 펌프 이론 유량은 약 0.962 mL/s이다. | 주사기 단면적 × 피스톤 속도로 산출 | PDF 추출 `/tmp/auto_titration_pdf_extract.txt`:44; `docs/report_laptop_app_development_draft.md`:25 | 0.962 자체만 쓰지 말고 산출 이유를 함께 쓰기 |
| 0.962 mL/s 산출은 주사기 내경 약 35 mm, STEP 100 step/s, 200 step/rev, T8 2 mm/rev에서 나온 약 1 mm/s 피스톤 속도에 기반한다. | 계산식 `Q=A×v`로 본문에 제시 | `docs/report_laptop_app_development_draft.md`:25, 펌웨어 `auto_titrator/arduino_stepper/arduino_stepper.ino`:38-41 | full-step 기준 계산임을 분명히 하기 |
| 펌프는 물 주입 실험 5회로 실제 토출량을 확인했고 거의 정확히 보정하였다. | 오차 분석에서 펌프를 중심 실패 원인에서 제외하는 근거로 사용 | 사용자 제공 최신 사실, `docs/report_laptop_app_development_draft.md`:91 | “펌프가 전혀 오차 없음”이 아니라 주된 실패 원인이 아니라고 쓰기 |
| Windows 앱은 일반 카메라, Mini2 열화상, 아두이노 펌프, 화학 계산, CSV 기록을 통합한다. | 앱 개발의 중심 성과로 설명 | `docs/report_laptop_app_development_draft.md`:5-39, 117; `auto_titrator/data_schema.py`:1-42 | 컬럼명을 그대로 나열하지 말고 한국어로 설명 |
| CSV에는 실험 조건, pKa/pKb, 지시약, pH 모델값, 이론 당량점, 펌프 상태, 색/열 변화, ROI 신뢰도, 예측 결과가 저장된다. | 데이터 기록 구조로 설명 | `docs/report_laptop_app_development_draft.md`:9-39, `auto_titrator/data_schema.py`:1-42, 226-228 | 내부 변수명 대신 의미 중심 |
| Mini2는 raw frame과 섭씨 온도 행렬을 기록한다. | 열화상 분석 섹션에 포함 | `docs/report_laptop_app_development_draft.md`:31-35 | 상용 표준계측기급 정확도처럼 과장하지 않기 |
| Android 앱은 WebView로 웹 UI를 쓰고 CameraX, USB-C Mini2, Bluetooth 펌프, Downloads CSV 저장을 처리한다. | Android 앱 개발 성과로 설명 | `docs/report_laptop_app_development_draft.md`:101-117, `mobile/android/README.md`:1-12 | `mobile/android/README.md`:18에는 과거 raw guard 문구가 있으므로 최신 사용자 확인을 우선 반영 |
| Android Mini2 섭씨 온도 수집은 실기기에서 확인되었다. | “Android에서도 Mini2 섭씨 온도값을 수집한다”로 표현 | 사용자 제공 최신 확인, `docs/report_laptop_app_development_draft.md`:107, `.omx/plans/ralplan-handoff-science-fair-report-rewrite-20260602.md`:46, 118-121 | 변환 경로와 보정 기록은 밝히되 계측 정확도 과장 금지 |
| Android 펌프는 Bluetooth Classic SPP로 `a/b/c/s/r` 명령을 보낸다. | 모바일 펌프 제어 설명 | `docs/report_laptop_app_development_draft.md`:109, `mobile/android/app/src/main/java/kr/auto/titration/mobile/pump/ManualPumpController.kt`:25-31, 136-153 | 자동 정지 기능처럼 쓰지 않기 |
| 머신러닝은 프레임별 분류가 아니라 실험 단위 당량점 부피 예측이다. | ML 분석 방법 핵심 문장 | `docs/report_laptop_app_development_draft.md`:43-51, `docs/ml_equivalence_result_detailed_summary.md`:37-43 | 25 fps 프레임을 독립 실험처럼 쓰지 않기 |
| 모델 입력은 색 변화, 열 변화, 주입량 후보 등 실험 중 얻을 수 있는 값이다. | 정답 누수 방지 설명 | `docs/report_laptop_app_development_draft.md`:47-49, `docs/ml_equivalence_result_detailed_summary.md`:69, 247 | 이론 당량점·예측 오차·라벨은 입력값이 아니라고 설명 |
| 전체 ML 결과: 평균 기준 당량점 30.000000 mL, 평균 예측 30.263973 mL, MAE 2.306494 mL, RMSE 3.012460 mL, 상대오차 MAE 8.810450%. | 결과 표와 본문에 정확히 기재 | `docs/report_laptop_app_development_draft.md`:55, `docs/ml_12_run_full_results.md`:20-28 | 숫자 반올림 시 원문 수치도 부록/표에 남기기 |
| 강산-강염기는 MAE 0.344194 mL, 상대오차 1.345296%로 가장 안정적이다. | 결과 해석의 긍정 사례 | `docs/report_laptop_app_development_draft.md`:57-62, 81; `docs/ml_12_run_full_results.md`:49-58 | 전체 시스템이 모든 조건에서 고정밀이라고 확대 금지 |
| 농도 조건별 예측표를 포함한다. | 결과 섹션의 상세 표 | `docs/report_laptop_app_development_draft.md`:64-83, `docs/ml_12_run_full_results.md`:30-54 | `current_fusion`, `compact_plus` 등 내부명은 한국어 모델명으로 변환 |
| 약산/약염기 조건 오차는 농도 조제와 표준용액 검증 부족이 가장 가능성 높은 원인이다. | 오차 분석의 결론 | `docs/report_laptop_app_development_draft.md`:87-95, `.omx/plans/prd-science-fair-report-rewrite-v2-20260602T023739Z.md`:7-9 | 확정 인과처럼 단정하지 말고 “가장 가능성 높은 원인”으로 표현 |
| PDF의 기존 결과표·100% 자동 인식·최대 5% 오차 통제 등은 실제 ML 결과와 맞지 않는다. | PDF 교체/삭제 사유 | PDF 추출 `/tmp/auto_titration_pdf_extract.txt`:79-92, `.omx/plans/ralplan-handoff-science-fair-report-rewrite-20260602.md`:44-48 | 최종 보고서에서는 실제 ML 수치로 대체 |
| 유사작품/차별성은 연속 주입, 색 변화, Mini2 열화상, 펌프 주입량, CSV, 앱/ML 통합 구조로 쓴다. | 차별성 섹션 | PDF 추출 `/tmp/auto_titration_pdf_extract.txt`:98, `.omx/plans/prd-science-fair-report-rewrite-v2-20260602T023739Z.md`:98 | DB/RISS 결과는 실제 검색 그림이나 간단 표로 보강 가능 |
| 생성형 AI 활용은 문서 정리와 코드 검토 보조로 한정한다. | AI 활용 범위 섹션 | `.omx/plans/prd-science-fair-report-rewrite-v2-20260602T023739Z.md`:2, 5.6; `.omx/plans/test-spec-science-fair-report-rewrite-v2-20260602T023739Z.md`:2 | 실험 데이터 생성/결과 조작으로 쓰지 않기 |
