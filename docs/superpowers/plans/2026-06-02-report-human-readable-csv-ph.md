# Report Human-Readable CSV and pH Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the app-development report so CSV fields are explained in Korean meaning rather than raw column-name dumps, and expand the chemistry/pH calculation explanation to match the implemented code.

**Architecture:** This is a documentation-only revision. Keep a few technical names only where useful for credibility, but make the main report readable to judges and students. Synchronize the updated draft into the existing final artifacts and verify that raw column-list style no longer dominates the report.

**Tech Stack:** Markdown, local repo evidence from Python chemistry/CSV code and Android/Windows app code, shell-based text verification.

---

## File Structure

- Modify: `docs/report_laptop_app_development_draft.md`
  - Main report draft. Replace long backtick column lists with Korean explanations and add richer pH model text.
- Modify: `_workspace/2026-06-02-001/final.md`
  - Existing final artifact. Copy updated draft here.
- Modify: `_workspace/2026-06-02-002/final.md`
  - Existing Humanize Korean artifact. Copy updated draft here.
- Reference only: `auto_titrator/chemistry.py`
  - Evidence for equivalence volume, unknown concentration, pH, ionic strength, Davies reliability.
- Reference only: `auto_titrator/chemical_constants.py`, `auto_titrator/indicator_models.py`
  - Evidence for IUPAC pKa lookup and indicator transition ranges.
- Reference only: `auto_titrator/data_schema.py`, `mobile/android/app/src/main/java/kr/auto/titration/mobile/data/CsvSchema.kt`
  - Evidence for stored CSV categories.

### Task 1: Replace raw CSV column dumps with Korean meaning groups

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Identify backtick-heavy paragraphs**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
text = Path('docs/report_laptop_app_development_draft.md').read_text(encoding='utf-8')
for i, line in enumerate(text.splitlines(), 1):
    if line.count('`') >= 6:
        print(i, line[:180])
PY
```
Expected: It prints the paragraphs that currently read like raw schema dumps.

- [ ] **Step 2: Replace experiment/chemistry CSV field list with readable text**

Use Korean explanation like:
```markdown
CSV에는 먼저 실험 기본 정보가 들어간다. 시료 이름, 시료 농도, 시료 부피, 시료의 산·염기 가수, 표준용액 이름, 표준용액 농도, 표준용액 가수, 적정 종류, 지시약, 사용한 계산 모델을 한 행마다 같이 저장하였다. 이렇게 한 이유는 같은 영상 데이터라도 농도와 물질 조건이 다르면 당량점 위치와 pH 변화가 달라지기 때문이다.
```

- [ ] **Step 3: Replace ROI/mask column list with readable text**

Use Korean explanation like:
```markdown
ROI 정보는 좌표 숫자만 저장한 것이 아니라, 어떤 방식으로 영역을 잡았는지도 함께 남겼다. 예를 들어 사용자가 직접 네모로 지정했는지, YOLO 후보가 잡은 영역인지, 마스크 면적이 충분한지, 후보 신뢰도가 어느 정도인지, 이전 프레임과 비교해 영역이 안정적인지를 기록하였다. 이 정보가 있어야 나중에 색 변화나 온도 변화가 실제 용액에서 나온 것인지, 잘못 잡힌 배경에서 나온 것인지 구분할 수 있다.
```

- [ ] **Step 4: Verify no raw schema dump remains in body**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
text = Path('docs/report_laptop_app_development_draft.md').read_text(encoding='utf-8')
heavy = [(i, line.count('`'), line[:120]) for i, line in enumerate(text.splitlines(), 1) if line.count('`') >= 10]
if heavy:
    raise SystemExit('backtick-heavy paragraphs remain: ' + repr(heavy[:5]))
print('OK readable report style')
PY
```
Expected: `OK readable report style`.

### Task 2: Expand pH, concentration, and indicator calculation explanation

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Replace short pH paragraph with full model explanation**

Use this structure:
```markdown
화학 계산은 단순히 당량점 부피만 구하는 수준으로 끝내지 않았다. 먼저 몰농도와 부피를 이용해 시료가 가진 산·염기 당량을 계산하고, 표준용액 농도와 가수를 이용해 이론적으로 필요한 표준용액 부피를 구하였다. 반대로 실험에서 얻은 당량점 부피를 넣으면 미지 시료 농도나 표준용액 농도를 역산할 수 있게 하였다.

pH 모델은 네 가지 적정 유형을 나누어 처리하였다. 강산-강염기에서는 당량점에서 산과 염기가 거의 완전히 중화되므로 pH 7을 기준값으로 둔다. 약산-강염기에서는 당량점 이후 용액에 약산의 짝염기가 남기 때문에, 선택된 pKa와 물의 이온곱을 사용해 염기성으로 치우치는 pH를 계산한다. 강산-약염기에서는 약염기의 짝산이 남는 상황을 pKb로 계산하여 산성 쪽 당량점 pH를 추정한다. 약산-약염기에서는 pKa와 pKb 차이가 pH를 좌우하므로 두 값을 함께 사용해 참고 pH를 계산한다.

또한 앱은 당량점에서 생긴 염의 농도와 이온 세기를 계산하고, Davies 활동도 보정의 신뢰 범위를 함께 표시하였다. 그래서 pH 값은 절대값처럼 단정하지 않고, 물질 조건과 이온 세기에 따라 어느 정도 신뢰할 수 있는 모델값인지 같이 남긴다.
```

- [ ] **Step 2: Add IUPAC and indicator explanation in human terms**

Use this structure:
```markdown
약산이나 약염기 계산에 필요한 pKa, pKb는 사용자가 직접 입력할 수도 있고, 앱에 포함된 IUPAC 해리상수 데이터에서 물질명을 검색해 선택할 수도 있다. 검색 결과가 여러 개이면 후보 수와 모호성 여부를 표시하고, 어떤 후보를 선택했는지 기록한다. 지시약은 페놀프탈레인, 메틸오렌지, BTB의 변색 pH 범위를 저장하여 실제 색 변화가 이론 당량점과 얼마나 가까운지 비교할 수 있게 하였다.
```

- [ ] **Step 3: Verify chemistry content terms**

Run:
```bash
rg -n "미지 시료 농도|표준용액 농도|강산-강염기|약산-강염기|강산-약염기|약산-약염기|이온 세기|Davies|IUPAC|페놀프탈레인|메틸오렌지|BTB" docs/report_laptop_app_development_draft.md
```
Expected: All chemistry concepts appear.

### Task 3: Sync artifacts and verify final readability

**Files:**
- Modify: `_workspace/2026-06-02-001/final.md`
- Modify: `_workspace/2026-06-02-002/final.md`

- [ ] **Step 1: Copy updated draft to final artifacts**

Run:
```bash
cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-001/final.md
cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-002/final.md
```
Expected: No output.

- [ ] **Step 2: Verify readable Korean and feature coverage**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
required = [
    '시료 이름', '표준용액 농도', '색 변화가 실제 용액에서 나온 것인지',
    '강산-강염기', '약산-강염기', '강산-약염기', '약산-약염기',
    '이온 세기', 'Davies', 'Bluetooth Classic SPP', 'Downloads 폴더',
]
for path in [Path('docs/report_laptop_app_development_draft.md'), Path('_workspace/2026-06-02-001/final.md'), Path('_workspace/2026-06-02-002/final.md')]:
    text = path.read_text(encoding='utf-8')
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f'{path}: missing ' + ', '.join(missing))
print('OK readable Korean report synced')
PY
```
Expected: `OK readable Korean report synced`.

## Self-Review

- Spec coverage: Replaces unreadable raw field lists, keeps CSV meaning, expands pH and chemistry modeling, keeps Android/Mini2/pump coverage.
- Placeholder scan: No TBD/TODO/fill-in placeholders.
- Type consistency: This plan edits prose only and references existing report files.
