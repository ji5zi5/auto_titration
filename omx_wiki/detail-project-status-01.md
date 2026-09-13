---
title: "detail-project-status-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:12.668Z
updated: 2026-09-10T11:10:12.668Z
sources: []
links: ["detail-project-status-01-part-2.md", "detail-project-status-01-part-3.md", "detail-project-status-01.md", "detail-project-status-02.md", "detail-project-status-03.md", "detail-project-status-04.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-project-status-01

## 문서의 역할과 해석
통합 현황 원문. 작성시점이 다른 단락과 완료/미완료 표현을 구별.

원문: [docs/PROJECT_STATUS_AND_REMAINING_WORK.md](../docs/PROJECT_STATUS_AND_REMAINING_WORK.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-project-status-01]] / [[detail-project-status-02]] / [[detail-project-status-03]] / [[detail-project-status-04]]


분할 이어읽기: [[detail-project-status-01]] / [[detail-project-status-01-part-2]] / [[detail-project-status-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
# 자동 적정 프로젝트 진행 현황 및 남은 수정점

작성 기준: 2026-07-27
목적: Windows 쪽 Codex 또는 다른 개발자가 이 repo를 바로 이어받아, 현재까지 구현된 내용과 앞으로 수정해야 할 일을 헷갈리지 않도록 정리한다.
범위: Windows 수집 앱, Mini2 열화상 처리, Arduino 시린지 펌프, 화학 계산, 머신러닝, Android 포팅, 문서/포스터 작업을 모두 포함한다.

> **배포/거버넌스 경고 (G009, 2026-07-27):** 현재 작업 트리와 여기서
> 만드는 Android debug APK/source backup에는 HIKMICRO Viewer에서 추출한 공식
> DEX/native bytes 및 vendor 경로가 포함되어 있다. 이 트리는 **private lab
> use 전용이며 재배포 불가**로 취급한다. 현재 트리, APK, source backup을
> GitHub에 push하거나 release/웹/공유 드라이브 등에 publish하지 않는다.
> `-PhikmicroRedistributionApproved=true` 같은 boolean은 배포 권한이 아니며
> release/public packaging을 허용하지 않는다. 공개 배포는 별도 권한 검토와
> official bytes/vendor path를 제거한 별도 소스 트리에서만 다시 심사한다.

## 1. 프로젝트 목표 요약

이 프로젝트는 고등학교 과학전람회/발명품 프로젝트로, 산·염기 중화적정에서 사람이 뷰렛 콕을 직접 조절하고 지시약 색 변화를 눈으로 판단할 때 생기는 인적 오류를 줄이기 위한 자동 적정 보조 시스템이다.

핵심 아이디어는 다음과 같다.

- 뷰렛 대신 Arduino 기반 시린지 펌프가 적정액을 일정한 속도로 밀어 넣는다.
- 일반 카메라는 지시약 색 변화를 RGB/HSV 값으로 기록한다.
- HIKMICRO Mini2 V2 열화상 카메라는 용액 영역의 온도 변화를 기록한다.
- 펌프 작동 시간과 보정 유량으로 현재 주입량을 계산한다.
- 모든 값을 같은 실험 CSV에 저장한다.
- 녹화 종료 후 머신러닝 모델이 당량점에 가까운 주입 부피를 예측한다.
- 예측 당량점 부피를 이용해 미지 시료 농도, 예측 pH, 이론 pH 곡선 해석으로 이어지게 한다.

중요한 범위는 다음과 같다.

- 완전 자동 적정기가 아니라 자동 적정 보조장치다.
- 모델이 당량점이라고 판단해도 펌프를 자동 정지하지 않는다.
- 현재 안전 설계는 사람이 녹화 시작/종료와 펌프 정지를 최종 판단하는 방식이다.
- 과장하면 안 되는 부분은 Android 단독 Mini2 섭씨 변환과 머신러닝 성능이다. Windows 쪽 공식 DLL 기반 온도 변환과 개발셋 머신러닝 결과는 구분해야 한다.

## 2. 현재 repo와 실행 상태

### 2.1 저장소

- GitHub repo: `https://github.com/ji5zi5/auto_titration`
- Windows 실행본 release: `v0.1.3 Windows 실행본`
- release URL: `https://github.com/ji5zi5/auto_titration/releases/tag/v0.1.3`
- 위 URL은 과거 Windows 상태 기록이다. 현재 official-byte Android 작업 트리를
  push/publish해도 된다는 뜻이 아니다.

### 2.2 사용자가 실제로 실행하는 Windows 경로

Windows에는 프로젝트 폴더를 하나만 둔다.

```text
C:\Users\Jio\Downloads\auto_titration
```

WSL에서는 다음 경로로 접근한다.

```text
/mnt/c/Users/Jio/Downloads/auto_titration
```

예전에 쓰던 `auto_titration_20260513-170048`, `auto_titration_windows` 같은 중복 폴더는 삭제 대상이다. 새 Codex가 작업할 때도 복사본을 새로 만들지 말고 위 폴더 하나만 사용한다.

### 2.3 일반 실행법

일반 사용자는 Windows에서 아래 파일을 더블클릭한다.

```text
launchers\windows\21_open_dashboard_server.bat
```

이 BAT가 하는 일은 다음과 같다.

- Python 실행기 탐색
- requirements 설치 확인
- YOLO 사용 시 requirements-yolo 설치 확인
- 기존 collector/server 프로세스 정리
- 대시보드 서버 실행
- live collector 실행
- 웹 UI 열기
- 같은 Wi-Fi에서 폰으로 접속할 수 있는 LAN 주소 출력

수집기만 따로 확인할 때는 다음을 실행한다.

```text
launchers\windows\20_windows_live_collect.bat
```

### 2.4 현재 실사용 기준

현재 실험 수집의 본경로는 Windows 노트북 앱이다. Android 앱은 상당히 많은 파일과 native library, bridge 코드가 있지만 아직 Windows와 같은 수준의 완전한 실사용 본경로라고 보면 안 된다. Android는 이어서 수정해야 할 대상이다.

Android의 현재 허용 범위는 private debug/lab sideload와 host-side software
verification뿐이다. `mobile/android/app/build.gradle.kts`는 manifest-matching
official bytes 및 official/vendor source path가 있는 동안 release/public packaging을
fail-closed로 차단한다. `:app:auditPublicDeliverable`은 로컬에서 같은 내용을
비파괴적으로 점검하며, 현재 트리에서는 실패가 정상이다.

## 3. 지금까지 구현한 것

## 3.1 Windows 대시보드와 live collector

구현된 핵심 파일은 다음과 같다.

```text
tools/dashboard_server.py
tools/windows_live_collect.py
website/index.html
website/app.js
website/style.css
```

구현된 기능은 다음과 같다.

- 브라우저 기반 실험 UI 제공
- 일반 카메라 프레임 표시
<!-- END SOURCE EXCERPT -->

