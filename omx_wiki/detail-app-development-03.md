---
title: "detail-app-development-03"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:25.777Z
updated: 2026-09-10T11:10:25.777Z
sources: []
links: ["detail-app-development-01.md", "detail-app-development-02.md", "detail-app-development-03.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-app-development-03

## 문서의 역할과 해석
앱 기능 설명 초안. 구현·UI·하드웨어 검증 주장에 작성시점 주의.

원문: [docs/report_laptop_app_development_draft.md](../docs/report_laptop_app_development_draft.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-app-development-01]] / [[detail-app-development-02]] / [[detail-app-development-03]]

<!-- BEGIN SOURCE EXCERPT -->
Android 앱에서도 USB-C Mini2에서 열화상 프레임과 섭씨 온도값을 수집한다. 앱은 USB 권한 상태, Mini2 연결 여부, thermal stream 시작 상태를 화면에 표시하고, Mini2에서 들어오는 열화상 프레임을 HIKMICRO 변환 경로로 처리해 온도 변화와 ROI별 열 특징값을 기록한다. 모바일 CSV에는 열화상 데이터의 출처, ROI 평균 온도, ROI 최고 온도, ROI 최저 온도, 전체 행렬 평균 온도, 열화상 행렬 크기, raw ROI 평균값, raw ROI 최솟값, raw ROI 최댓값, raw ROI 표준편차, raw ROI 변화량, raw ROI 중앙값, raw ROI 사분위 범위, 전체 raw 평균값, 전체 raw 최솟값, 전체 raw 최댓값, 전체 raw 표준편차, 사용한 온도 변환 방식, 보정 여부가 기록된다. 즉 Android 앱은 단순히 raw frame만 저장하는 것이 아니라, 실기기에서 확인한 섭씨 온도 수집 결과도 함께 남길 수 있게 구성하였다.

펌프는 Android에서도 블루투스로 연결할 수 있게 하였다. 앱은 Bluetooth Classic SPP 방식으로 HC-05, HC-06, Arduino, ESP32 계열 장치를 찾고, 펌프 명령은 a, b, c, s, r 체계로 보낸다. a는 역방향, b는 정방향, c는 정지, s는 상태 확인, r은 리셋이다. Android CSV에는 펌프가 몇 스텝 움직였는지, 펌웨어가 확인한 스텝 수가 얼마인지, 펌웨어가 계산한 주입 부피가 얼마인지, 마지막 상태 응답이 무엇인지, 펌프가 움직인 시간, 이론 당량점까지 걸리는 예상 시간, 당량점까지 남은 시간, 당량점 허용 범위, 현재 위치가 당량점 근처인지 여부가 같이 남는다. 녹화가 끝나면 앱은 CSV를 스마트폰 Downloads 폴더에 auto-titration-android-run 형식의 파일로 저장한다.

Android 앱에서도 ROI 검사를 녹화 전에 수행한다. 사용자가 직접 지정한 ROI나 YOLO 기반 후보 ROI를 사용하고, ROI가 준비되지 않은 상태에서는 녹화가 시작되지 않도록 하였다. Android는 ROI가 네모 영역인지 마스크 영역인지, 일반 카메라와 열화상에서 각각 어떤 방식으로 잡혔는지, 마스크 면적이 얼마인지, 후보 신뢰도가 어느 정도인지, 영역이 여러 조각으로 나뉘었는지, 프레임 사이에서 안정적으로 유지되는지를 기록한다. 이 방식은 노트북 앱의 ROI 기록 방식과 맞추기 위한 것이다.

Android 앱은 스마트폰 단독 수집을 염두에 두고 만들었지만, 현재 실험에서는 노트북 앱을 보조하는 역할도 함께 맡는다. 스마트폰에서 얻은 카메라 프레임, Mini2 열화상 프레임, 온도 변화, ROI 정보, 펌프 상태는 노트북 대시보드와 같은 데이터 구조에 맞춰 처리된다. 최종 CSV와 머신러닝 학습 데이터 형식도 노트북 앱과 연결될 수 있도록 설계하였다. 그 결과 Android 앱은 기존 노트북 앱의 기능을 모바일 환경으로 확장하고, 스마트폰 카메라 권한, USB-C 센서 권한, 블루투스 권한을 활용한 추가 개발 결과가 되었다.

## 짧은 요약문

본 연구에서는 적정 실험 데이터를 체계적으로 수집하기 위해 Windows 노트북 앱과 Android 앱을 개발하였다. 노트북 앱은 일반 카메라의 색 변화, Mini2 열화상 카메라의 raw 열 변화와 섭씨 온도 변화, 아두이노와 직접 연결된 시린지 펌프의 주입량 정보를 같은 시간축으로 기록한다. CSV에는 실험 조건, 농도 계산값, 이론 당량점, 이론 pH 곡선, IUPAC pKa 후보, 지시약 변색 범위, 펌프 상태, 주입량, 색상 변화, 열화상 변화, ROI 신뢰도, 동기화 품질, 머신러닝용 파생 특징, 예측 결과가 함께 저장된다. 머신러닝 분석은 프레임별 상태 분류가 아니라 실험 하나당 최종 당량점 부피 하나를 예측하는 방식으로 구성하였다. 실제 실험 데이터를 이용한 초기 분석에서 전체 MAE는 2.306494 mL, 상대오차 MAE는 8.810450%였고, 강산-강염기 조건에서는 MAE 0.344194 mL, 상대오차 1.345296%로 가장 안정적인 결과를 보였다. Android 앱은 같은 웹 UI를 WebView로 사용하면서 스마트폰 카메라, USB-C Mini2 열화상 및 섭씨 온도 수집, Bluetooth Classic SPP 펌프 제어, Downloads 폴더 CSV 저장을 모바일 환경에서 수행하도록 만들었다. 오차 분석에서는 약산·약염기 조건의 큰 오차를 모델 문제만으로 단정하지 않고, 용액 농도 조제 오차와 표준용액 농도 검증 부족을 주된 원인으로 정리하였다. 펌프는 물 주입 실험을 5회 반복해 목표 주입량과 거의 일치하도록 보정하였다. 두 앱 모두 센서 데이터를 분석 가능한 형태로 남기는 데 초점을 두었다. 안전을 위해 펌프는 자동 정지하지 않고 사람이 직접 제어하도록 설계하였다.
<!-- END SOURCE EXCERPT -->

