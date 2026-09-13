---
title: "detail-windows-handoff-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:11.655Z
updated: 2026-09-10T11:10:11.655Z
sources: []
links: ["detail-windows-handoff-01-part-2.md", "detail-windows-handoff-01-part-3.md", "detail-windows-handoff-01.md", "detail-windows-handoff-02.md", "detail-windows-handoff-03.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-windows-handoff-01

## 문서의 역할과 해석
운영 인수인계 이력. 날짜·배포 경로는 실행본과 재확인.

원문: [docs/WINDOWS_CODEX_HANDOFF.md](../docs/WINDOWS_CODEX_HANDOFF.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-windows-handoff-01]] / [[detail-windows-handoff-02]] / [[detail-windows-handoff-03]]


분할 이어읽기: [[detail-windows-handoff-01]] / [[detail-windows-handoff-01-part-2]] / [[detail-windows-handoff-01-part-3]]
<!-- BEGIN SOURCE EXCERPT -->
# Windows Codex 인수인계 문서

작성 기준: 2026-07-14
대상: 이 프로젝트를 처음 보는 Windows 쪽 Codex 또는 새 개발자
목적: 프로젝트가 무엇인지, 어떤 파일을 실행해야 하는지, 어디를 수정해야 하는지 한 번에 이해하게 하는 문서

더 긴 전체 현황은 `docs/PROJECT_STATUS_AND_REMAINING_WORK.md`에 있다. 이 문서는 먼저 읽는 빠른 인수인계 문서다.
25 fps 수집 구조와 검증 수치는 `docs/LIVE_PERFORMANCE_VALIDATION.md`에 정리되어 있다.
자동정지 구조와 재생 검증은 `docs/AUTO_STOP_VALIDATION.md`에 정리되어 있다.

### 2026-07-14 자동정지 추가

Windows 웹 앱에는 기본 OFF인 지속 색 변화 자동정지가 추가되었다. 구현은 `auto_titrator/auto_stop.py`, 서버 연결은 `tools/windows_live_collect.py`, UI는 `website/index.html`과 `website/app.js`에 있다. 일반 카메라 ROI의 초기색을 1초간 보정하고, 실시간 구간 분류기 점수와 실제 색 변화가 함께 확인된 뒤 색 변화가 0.4초 유지되면 펌프에 `c`를 보낸다. 감지·정지 시점과 명령 결과는 CSV에 남으며 이론 당량점은 정지 조건으로 사용하지 않는다.

## 0. 가장 먼저 알아야 할 결론

이 프로젝트는 고등학교 과학전람회용 `스마트 자동 적정 보조장치`다.

중화적정에서 사람이 뷰렛 콕을 계속 조절하고, 지시약 색 변화만 보고 종말점을 판단하면 오차가 생긴다. 이 프로젝트는 그 과정을 데이터로 기록하고, 머신러닝으로 당량점에 가까운 주입 부피를 예측해서 미지 용액 농도를 계산하려는 시스템이다.

현재 실사용 중심은 Windows 노트북 앱이다.

- Arduino 시린지 펌프가 적정액을 밀어 넣는다.
- 일반 카메라가 지시약 색 변화를 기록한다.
- HIKMICRO Mini2 V2 열화상 카메라가 용액 온도 변화를 기록한다.
- Windows 웹 대시보드가 카메라, 열화상, 펌프, 실험 조건, CSV 저장을 한 화면에서 다룬다.
- 녹화 종료 후 live 머신러닝 모델이 예측 당량점 부피를 계산한다.
- 예측 당량점 부피로 농도와 예측 pH를 계산한다.

자동정지는 선택 기능이며 기본값은 꺼짐이다. 체크하지 않으면 펌프 시작과 정지는 사람이 버튼으로 수행한다. 체크하면 지속 색 변화가 확인될 때 앱이 정지 명령을 보내지만, 실제 습식 정지 정확도와 PC 장애 시 안전성은 아직 별도 검증 대상이다.

## 1. 현재 작업 폴더

Windows에는 프로젝트 폴더를 하나만 둔다.

```text
C:\Users\Jio\Downloads\auto_titration
```

WSL 원본 repo는 다음이다.

```text
/home/jio/code/auto_titration
```

둘 다 git repo다. Windows 쪽에서 작업할 때는 `C:\Users\Jio\Downloads\auto_titration`만 사용한다. 새 폴더를 또 만들지 않는다.

WSL에서 Windows 폴더를 볼 때는 다음 경로다.

```text
/mnt/c/Users/Jio/Downloads/auto_titration
```

현재 GitHub repo는 다음이다.

```text
https://github.com/ji5zi5/auto_titration
```

최신 commit은 아래 명령으로 확인한다. 이 문서 자체도 repo에 포함되어 있으므로, 작업 전에는 `git pull` 후 최신 상태를 기준으로 본다.

```bash
git log --oneline -1
```

## 2. 처음 실행할 때 할 일

Windows에서 아래 파일을 더블클릭한다.

```text
C:\Users\Jio\Downloads\auto_titration\launchers\windows\21_open_dashboard_server.bat
```

이 파일이 하는 일은 다음과 같다.

- Python 실행기를 찾는다.
- 필요한 Python 패키지를 설치하거나 확인한다.
- 이전에 떠 있던 dashboard/collector 프로세스를 정리한다.
- 웹 대시보드 서버를 연다.
- 실시간 수집기를 실행한다.
- 브라우저에서 실험 화면을 열 수 있게 한다.

정상적으로 켜지면 보통 다음 주소가 쓰인다.

```text
대시보드: http://127.0.0.1:8765/
수집기:   http://127.0.0.1:8766/
```

같은 Wi-Fi의 휴대폰에서 노트북 대시보드에 접속하려면 BAT가 출력하는 LAN 주소를 쓴다.

```text
http://<노트북 IP>:8765
```

수집기만 따로 확인할 때는 다음 파일을 실행한다.

```text
launchers\windows\20_windows_live_collect.bat
```

## 3. 전체 작동 흐름

실험 흐름은 아래 순서로 이해하면 된다.

```text
1. 사용자가 Windows 대시보드 실행
2. 일반 카메라와 Mini2 열화상 카메라 표시
3. 일반 카메라 ROI와 열화상 ROI 지정
4. 실험 조건 입력
5. 녹화 시작 버튼 클릭
6. CSV 기록 시작 + 펌프에 b 명령 전송
7. 실험 중 색 변화, 온도 변화, 주입량 저장
8. 녹화 종료 버튼 클릭
9. CSV 기록 종료 + 펌프에 c 명령 전송
10. 머신러닝 모델이 예측 당량점 부피 계산
11. 앱이 예측 농도와 예측 pH 표시
```

핵심은 모든 데이터가 CSV로 남는다는 점이다. CSV가 제대로 저장되어야 머신러닝과 보고서 분석이 가능하다.

## 4. 하드웨어 구성

## 4.1 시린지 펌프

사용 장치:

- Arduino UNO
- A4988 스테퍼 모터 드라이버
- 스테퍼 모터
- T8 리드스크류
- anti-backlash nut
- 100 mL 주사기
- 실리콘 호스
- 외부 전원

<!-- END SOURCE EXCERPT -->

