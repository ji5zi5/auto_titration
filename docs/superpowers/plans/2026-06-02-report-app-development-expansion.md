# Report App Development Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen the report's app-development section by adding Arduino pump linkage, pump-volume logging, and Mini2 temperature/raw analysis methodology.

**Architecture:** Keep one report draft file as the source of truth and add concise, evidence-aligned paragraphs under the laptop and Android sections. Avoid claiming fully automatic pump stopping or fully validated Android Celsius conversion. Preserve the existing report tone.

**Tech Stack:** Markdown report draft, Windows Python collector, Web dashboard, Arduino serial pump, HIKMICRO Mini2 raw frame analysis, Android WebView/CameraX/USB host.

---

### Task 1: Add Arduino Pump Integration To Laptop App Section

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Add a paragraph explaining direct Arduino pump linkage**

Insert after the existing pump paragraph:

```markdown
노트북 앱은 아두이노와 직접 연결되어 펌프 상태를 함께 기록한다. 아두이노는 시린지 펌프의 스테퍼 모터를 제어하고, 노트북 앱은 사용자가 보낸 펌프 명령과 시간 정보를 기준으로 예상 주입량을 계산한다. 실험 중에는 펌프가 어느 방향으로 동작했는지, 경과 시간이 얼마인지, 설정한 유량에 따라 용액이 얼마나 주입되었는지를 CSV에 함께 남긴다. 이 정보가 있어야 색 변화나 열 변화가 나타난 순간을 실제 주입 부피와 연결할 수 있다.
```

- [ ] **Step 2: Verify report does not claim unsafe automatic pump stop**

Run: `grep -n "자동 정지\|직접 제어\|아두이노" docs/report_laptop_app_development_draft.md`
Expected: text says pump stop remains human-controlled.

### Task 2: Add Mini2 Temperature/Raw Analysis Methodology

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Add a paragraph explaining thermal raw analysis**

Insert after the Mini2 raw frame paragraph:

```markdown
온도 분석은 실시간 수집 단계와 사후 검증 단계를 나누어 처리하였다. 실시간 수집 중에는 Mini2 raw 행렬에서 ROI의 평균, 표준편차, 중앙값, 사분위 범위, 이전 프레임과의 변화량을 계산해 열 변화 추세를 저장하였다. 검증된 섭씨 변환값이 필요한 경우에는 HIKMICRO 공식 변환 경로를 이용해 raw 값을 온도값으로 해석하는 후처리 과정을 사용한다. 즉, 실험 중에는 속도와 안정성을 위해 raw 기반 특징값을 우선 저장하고, 온도 단위 해석은 검증 가능한 단계에서 따로 확인하도록 설계하였다.
```

- [ ] **Step 2: Verify Celsius is not overclaimed**

Run: `grep -n "섭씨\|raw\|공식" docs/report_laptop_app_development_draft.md`
Expected: Android Celsius is described as unvalidated until real-device verification; Windows path says official conversion is used for validation/post-processing.

### Task 3: Add Android Pump And Thermal Parity Caveat

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Add Android paragraph for mobile expansion**

Append to Android section:

```markdown
Android 앱에서도 펌프와 센서 정보를 같은 형식으로 다루도록 구성하였다. 다만 실제 실험에서 펌프와 Mini2의 안정성이 가장 중요한 부분이므로, Android 앱은 연결 상태와 raw 데이터 수집 가능 여부를 화면에 명확히 표시하고, 검증되지 않은 값은 확정된 온도나 성공 상태로 표시하지 않도록 하였다. 이 방식은 노트북 앱과 같은 데이터 구조를 유지하면서도 모바일 환경에서 발생할 수 있는 USB 권한, 센서 연결, native stream 오류를 실험자가 바로 확인할 수 있게 한다.
```

- [ ] **Step 2: Verify summary includes pump and temperature analysis**

Run: `tail -n 12 docs/report_laptop_app_development_draft.md`
Expected: short summary mentions Arduino pump and Mini2 raw/temperature analysis.

### Task 4: Humanize And Save Final Draft

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`
- Create/Update: `_workspace/2026-06-02-001/final.md`

- [ ] **Step 1: Reduce repetitive report phrasing**

Rewrite only style spans while preserving technical claims, names, numbers, and safety caveats.

- [ ] **Step 2: Save Humanize Korean artifact**

Run: `cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-001/final.md`
Expected: final artifact mirrors the updated report draft.
