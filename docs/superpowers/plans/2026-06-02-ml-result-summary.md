# ML Result Summary Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a clear Korean science-fair-ready explanation of how the equivalence-point ML evaluation was performed and what results were obtained.

**Architecture:** Use existing generated ML artifacts as the source of truth, especially `report.md`, `typewise_run_metrics.csv`, and selected-model prediction CSVs. Write a standalone documentation file that separates method, inputs, validation design, numeric results, limitations, and presentation wording.

**Tech Stack:** Markdown documentation, Python CSV/JSON inspection, existing `auto_titrator.ml_curve_equivalence` outputs.

---

### Task 1: Confirm Source Artifacts

**Files:**
- Read: `data/ml/curve_equivalence_current/report.md`
- Read: `data/ml/curve_equivalence_current/typewise_run_metrics.csv`
- Read: `data/ml/curve_equivalence_current/predictions/*/*.csv`

- [ ] **Step 1: Verify required generated outputs exist**

Run:

```bash
test -s data/ml/curve_equivalence_current/report.md
test -s data/ml/curve_equivalence_current/typewise_run_metrics.csv
test -d data/ml/curve_equivalence_current/predictions
```

Expected: all commands exit with code 0.

- [ ] **Step 2: Extract selected run-level prediction rows**

Run:

```bash
source .venv/bin/activate
python - <<'PY'
import csv, json
from pathlib import Path
summary = json.loads(Path('data/ml/curve_equivalence_current/curve_equivalence_summary.json').read_text(encoding='utf-8'))
for titration_type, payload in summary['types'].items():
    selected = payload['selected_model']['feature_set']
    for path in sorted((Path('data/ml/curve_equivalence_current/predictions') / titration_type).glob(f'*-{selected}.csv')):
        rows = list(csv.DictReader(path.open(encoding='utf-8')))
        if rows:
            row = rows[0]
            print(titration_type, selected, row['actual_equivalence_volume_ml'], row['predicted_equivalence_volume_ml'], row['absolute_error_ml'], row['absolute_error_percent_of_equivalence'])
PY
```

Expected: 12 selected predictions, one per run.

### Task 2: Write Detailed Korean Summary

**Files:**
- Create: `docs/ml_equivalence_result_detailed_summary.md`

- [ ] **Step 1: Create the document with fixed sections**

Write these sections in order:

```markdown
# 머신러닝 당량점 예측 결과 상세 정리

## 1. 분석 목적
## 2. 사용한 데이터
## 3. 머신러닝 문제 정의
## 4. 입력 feature와 target
## 5. 학습/검증 방식
## 6. 비교한 모델 feature set
## 7. 전체 결과
## 8. 타입별 결과
## 9. run별 예측 결과
## 10. 결과 해석
## 11. 전람회 발표에서 안전한 표현
## 12. 현재 한계와 다음 개선 방향
```

- [ ] **Step 2: Include exact numeric results**

Use values from `typewise_run_metrics.csv` and selected prediction CSVs. Do not invent improved scores.

- [ ] **Step 3: Explicitly mark limitations**

Include:

```markdown
- 타입별 run이 3개뿐이라 성공률은 0/3, 1/3, 2/3, 3/3 형태의 참고 지표이다.
- 현재 결과는 proof-of-concept이며 일반화 정확도라고 주장하면 안 된다.
- 강산-강염기는 성능이 좋지만 약산/약염기 계열은 추가 데이터와 모델 개선이 필요하다.
```

### Task 3: Verify Documentation

**Files:**
- Read: `docs/ml_equivalence_result_detailed_summary.md`

- [ ] **Step 1: Check key claims are present**

Run:

```bash
grep -q '전체 MAE: 2.306494 mL' docs/ml_equivalence_result_detailed_summary.md
grep -q '강산-강염기' docs/ml_equivalence_result_detailed_summary.md
grep -q '주작' docs/ml_equivalence_result_detailed_summary.md || true
```

Expected: first two commands pass. Third command may pass or fail; the document should avoid encouraging fabrication.

- [ ] **Step 2: Confirm no fabricated improvement claim exists**

Run:

```bash
! grep -E '완성된 실사용 모델|모든 조건에서 우수|약산.*정확' docs/ml_equivalence_result_detailed_summary.md
```

Expected: exit code 0.
