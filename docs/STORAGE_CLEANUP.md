# 저장공간 정리 기록

실행일: 2026-09-13T16:08:35

## 결과
- Windows C: 여유 0.66 GiB → 3.78 GiB; 순증 약 3.12 GiB.
- WSL 파일시스템 여유 순증 약 3.58 GiB.
- WSL 내부 공간 회수와 Windows 호스트의 VHDX 크기 감소는 별개다. VHDX 압축·WSL 종료·설정 변경은 하지 않았다.

## 삭제 범위
- Windows: 24시간 이상 지난 원격 데스크톱 ETL 진단 로그(최신 로그 보존), 이전 WSL 충돌 덤프 2개(최신 덤프 보존), pip/npm 다운로드 캐시, 프로젝트 Gradle 캐시·Android 중간파일.
- Windows: 24시간 이상 지난 NVIDIA/AMD 그래픽 셰이더 캐시. 사용 중/접근 거부 파일은 건너뜀.
- WSL: pip 다운로드 캐시, Go 빌드 캐시, Gradle 캐시, Android intermediates/kotlin/tmp 및 프로젝트 .gradle.
- 휴지통 이동 없이 영구 삭제했다. 개인 문서, 설치 프로그램, 알 수 없는 Downloads ZIP, 원본 실험 파일은 삭제하지 않았다.

## 보존·검증
- 원본 실험 CSV·최종보고서·모델·DLL·소스·APK 등 지정한 22개 파일의 SHA-256이 삭제 전후 모두 일치했다.
- 소스 변경 없이 캐시만 정리했으며, 정리 직후 git status가 정리 전과 일치했다.
- Python·가상환경·Android SDK·JDK·Gradle 실행기·vendor 라이브러리·모든 APK outputs·.git·.omx·위키는 보존했다.
- 다음 빌드나 실행 때 캐시 재생성/다운로드로 첫 실행이 느려질 수 있다. 전체 테스트와 하드웨어 시험은 이번 저장공간 정리 범위에 포함하지 않았다.
