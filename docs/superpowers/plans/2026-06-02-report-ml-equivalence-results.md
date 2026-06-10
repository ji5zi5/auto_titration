# ML Equivalence Results Report Addition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the machine-learning equivalence-point prediction methodology, results, and limitations from `docs/ml_equivalence_result_detailed_summary.md` into the app-development report.

**Architecture:** This is a documentation-only change. The report keeps the existing app-development structure, adds a dedicated run-level ML analysis section after the current ML feature paragraphs, and updates the short summary so the final report reflects actual model outputs rather than vague “prediction result” wording.

**Tech Stack:** Markdown documentation, Python-based text verification, existing report artifacts under `docs/` and `_workspace/`.

---

## File Structure

- Modify: `docs/report_laptop_app_development_draft.md`
  - Add a new subsection after the existing ML feature/prediction paragraphs and before ROI discussion.
  - Update `## 짧은 요약문` to mention run-level ML evaluation and the key numeric result.
- Modify: `_workspace/2026-06-02-001/final.md`
  - Keep synchronized with the report draft.
- Modify: `_workspace/2026-06-02-002/final.md`
  - Keep synchronized with the report draft.
- Reference only: `docs/ml_equivalence_result_detailed_summary.md`
  - Source for data counts, feature sets, metrics, type-wise results, and safe wording.

## Evidence to Preserve

- ML target is one final equivalence-point volume per run, not frame-level status classification.
- Data size is 12 runs: 4 titration types × 3 concentrations: 0.10 M, 0.15 M, 0.20 M.
- Inputs are measurable or computable during experiment: visible RGB/HSV, color changes, thermal ROI/raw summaries, candidate source/score/agreement/rank, run progress/injected volume.
- Leakage-risk values are excluded from model features: theoretical equivalence volume, distance to equivalence, prediction error, theoretical pH, endpoint labels, direct pKa-like target proxies.
- Validation is leave-one-run-out by concentration inside each titration type.
- Overall best-by-type result: 12 runs, MAE 2.306494 mL, RMSE 3.012460 mL, relative MAE 8.810450%, bias 0.263972 mL.
- Type-wise results:
  - strong acid–strong base: `current_fusion`, MAE 0.344194 mL, relative MAE 1.345296%.
  - strong acid–weak base: `current_fusion`, MAE 3.021775 mL, relative MAE 9.932038%.
  - weak acid–strong base: `compact_plus`, MAE 3.037659 mL, relative MAE 13.216226%.
  - weak acid–weak base: `current_fusion`, MAE 2.822347 mL, relative MAE 10.748239%.
- Interpretation: strong acid–strong base is the most successful condition; weak acid/weak base families remain preliminary because reactions can be less abrupt and data size is small.

---

### Task 1: Insert ML result section into the report

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Locate insertion point**

Run:
```bash
nl -ba docs/report_laptop_app_development_draft.md | sed -n '30,45p'
```

Expected: the current ML feature paragraphs are around lines 35-37 and ROI begins after them.

- [ ] **Step 2: Add this exact section after the paragraph ending with “모델 예측을 한 행 단위로 비교할 수 있다.”**

Insert:
```markdown
머신러닝 분석은 프레임마다 `before`, `near_endpoint`, `endpoint` 같은 상태를 맞히는 방식이 아니라, 실험 CSV 하나를 하나의 run으로 보고 최종 당량점 부피 하나를 예측하는 방식으로 설계하였다. 즉 모델의 질문은 “이 실험에서 당량점은 몇 mL 지점인가?”이다. 앱은 먼저 run 내부의 주입량-센서값 곡선을 만들고, 색 변화가 큰 지점, 열 변화가 큰 지점, 색과 열 변화가 동시에 강한 지점을 각각 당량점 후보로 추출한다. 이후 각 후보 주변의 색상 변화 기울기, 열 변화 기울기, 곡률, 후보 점수, 후보 간 일치도, 후보 순위, run 진행 정보를 특징값으로 만들어 후보 중 실제 당량점에 가장 가까운 지점을 선택하도록 하였다.

분석에는 실제 실험 CSV 12개를 사용하였다. 강산-강염기, 강산-약염기, 약산-강염기, 약산-약염기 네 종류에 대해 각각 0.10 M, 0.15 M, 0.20 M 조건의 run을 사용하였다. 25 fps로 저장된 많은 프레임을 서로 독립적인 실험처럼 취급하지 않고, 하나의 CSV 전체를 하나의 실험 단위로 묶었다. 따라서 모델 평가는 프레임별 정확도가 아니라 run 단위의 당량점 부피 오차로 진행하였다.

모델 입력에는 실험 중 실제로 얻을 수 있는 값만 사용하였다. 일반 카메라에서는 RGB 채널 평균, HSV 평균, RGB/HSV 변화량, 색 변화 곡선의 기울기와 곡률을 사용하였다. 열화상에서는 ROI 평균·최대·최소 온도, 표준편차, 분위값, raw thermal ROI 분포, 열 변화 기울기와 곡률을 사용하였다. 여기에 후보 source가 color인지 thermal인지 fusion인지, 후보 점수와 후보 간 일치도, 후보 순위, 현재 주입량과 run 진행 정도를 함께 넣었다. 현재 주입량은 펌프 유량과 녹화 시간을 통해 실험 중 계산 가능한 값이므로 정답 누수가 아니라 장치가 실제로 제공하는 정보로 보았다.

반대로 이론 당량점 부피, 당량점까지의 거리, 예측 오차, 이론 pH, endpoint label, pKa를 정답처럼 직접 드러낼 수 있는 값은 모델 입력에서 제외하였다. 이 값들은 학습 정답이나 평가 기준으로만 사용하였다. 이렇게 한 이유는 모델이 화학 계산식을 그대로 읽어 답을 맞히는 것이 아니라, 색 변화·열 변화·주입량 정보의 조합으로 당량점 후보를 고르는지 확인하기 위해서이다.

데이터 수가 적기 때문에 train/test를 무작위로 섞지 않고, 같은 적정 종류 안에서 농도 하나를 빼고 검증하는 leave-one-run-out 방식을 사용하였다. 예를 들어 강산-강염기에서는 0.10 M run을 검증용으로 빼고 0.15 M과 0.20 M run으로 학습한 뒤, 같은 방식으로 0.15 M과 0.20 M도 각각 한 번씩 검증하였다. 이 과정을 네 적정 종류에 대해 반복하였다. 타입별 run이 3개뿐이므로 성공률은 통계적으로 강하게 해석하지 않고, 평균 절대오차, 상대오차, run별 예측값을 중심으로 해석하였다.

비교한 feature set은 여러 가지였다. `current_fusion`은 기존 색+열 융합 후보 모델이고, `compact_plus`는 후보 간 일치도, 순위, 밀도 정보를 추가한 모델이다. `compact_plus_no_progress`와 `fusion_no_progress`는 주입량과 진행 정보를 제거했을 때 센서 정보만으로 어느 정도 가능한지 보기 위한 비교 모델이다. `thermal_basic`, `thermal_expanded`, `color_expanded`, `fusion_expanded`는 열화상 또는 색상 특징값을 더 많이 넣었을 때의 효과를 확인하기 위한 모델이다. 분석 결과 현재 12개 run에서는 feature를 많이 늘린 모델이 항상 좋아지지는 않았고, 오히려 간결한 색+열 융합 후보 방식이 더 안정적인 경우가 있었다.

전체 12개 run에서 각 적정 종류별로 가장 낮은 MAE를 보인 feature set을 선택했을 때, 평균 실제 당량점 부피는 30.000000 mL이고 평균 예측 당량점 부피는 30.263973 mL였다. 전체 평균 절대오차는 2.306494 mL, median absolute error는 2.358796 mL, RMSE는 3.012460 mL였다. 상대오차 MAE는 8.810450%였고, 농도 환산 오차 MAE도 8.810450%로 나타났다. 이는 같은 반응식과 같은 표준용액 조건에서는 미지 농도가 당량점 부피에 비례하기 때문이다. 전체 bias는 0.263972 mL로, 평균적으로는 예측값이 실제 당량점보다 약간 크게 나온 정도였다.

적정 종류별 결과는 차이가 컸다. 강산-강염기 조건은 `current_fusion` feature set에서 MAE 0.344194 mL, 상대오차 MAE 1.345296%로 가장 안정적인 결과를 보였다. 강산-약염기는 `current_fusion`에서 MAE 3.021775 mL, 상대오차 MAE 9.932038%였고, 약산-강염기는 `compact_plus`에서 MAE 3.037659 mL, 상대오차 MAE 13.216226%였다. 약산-약염기는 `current_fusion`에서 MAE 2.822347 mL, 상대오차 MAE 10.748239%였다. 따라서 현재 결과는 모든 적정 종류에서 완성된 모델이라기보다, 강산-강염기 조건에서는 센서 융합 당량점 예측이 비교적 잘 작동했고 약산·약염기 조건에서는 추가 데이터와 모델 개선이 필요하다는 결과로 해석하였다.

run별로 보면 강산-강염기는 0.10 M에서 실제 20.000000 mL에 대해 20.560603 mL, 0.15 M에서 실제 30.000000 mL에 대해 29.936488 mL, 0.20 M에서 실제 40.000000 mL에 대해 39.591533 mL로 예측하였다. 반면 약산-강염기 0.10 M 조건에서는 실제 20.000000 mL에 대해 25.722220 mL로 예측하여 오차가 크게 나타났다. 약산-약염기에서도 0.15 M 조건은 30.000000 mL에 대해 29.974601 mL로 거의 맞았지만, 0.10 M과 0.20 M 조건에서는 오차가 컸다. 이 결과는 데이터 수가 적을 때 한 run의 실패가 평균 성능을 크게 흔들 수 있음을 보여준다.

최종적으로 전람회 보고서에서는 “센서만으로 당량점을 완벽하게 찾았다”고 표현하지 않고, “일반 카메라 색상 변화, Mini2 열화상 ROI 변화, 펌프 주입량 정보를 융합하여 당량점 후보를 추출하고, 머신러닝으로 후보 중 실제 당량점에 가까운 지점을 선택하였다”고 정리하였다. 현재 결과는 완성된 상용 수준 모델이 아니라, 센서 융합 자동 적정 보조장치가 당량점 예측에 활용될 수 있음을 보인 proof-of-concept로 해석하였다.
```

- [ ] **Step 3: Verify section content exists**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
text = Path('docs/report_laptop_app_development_draft.md').read_text(encoding='utf-8')
required = [
    '실험 CSV 하나를 하나의 run으로 보고 최종 당량점 부피 하나를 예측',
    '실제 실험 CSV 12개',
    '전체 평균 절대오차는 2.306494 mL',
    '강산-강염기 조건은 `current_fusion` feature set에서 MAE 0.344194 mL',
    'proof-of-concept',
]
for phrase in required:
    assert phrase in text, phrase
print('OK report ML section phrases present')
PY
```

Expected: `OK report ML section phrases present`.

---

### Task 2: Update short summary and synced workspace copies

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`
- Modify: `_workspace/2026-06-02-001/final.md`
- Modify: `_workspace/2026-06-02-002/final.md`

- [ ] **Step 1: Replace the short summary paragraph**

Replace the existing paragraph under `## 짧은 요약문` with:

```markdown
본 연구에서는 적정 실험 데이터를 체계적으로 수집하기 위해 Windows 노트북 앱과 Android 앱을 개발하였다. 노트북 앱은 일반 카메라의 색 변화, Mini2 열화상 카메라의 raw 열 변화와 섭씨 온도 변화, 아두이노와 직접 연결된 시린지 펌프의 주입량 정보를 같은 시간축으로 기록한다. CSV에는 실험 조건, 농도 계산값, 이론 당량점, 이론 pH 곡선, IUPAC pKa 후보, 지시약 변색 범위, 펌프 상태, 주입량, 색상 변화, 열화상 변화, ROI 신뢰도, 동기화 품질, 머신러닝용 파생 특징, 예측 결과가 함께 저장된다. 머신러닝 분석은 프레임별 상태 분류가 아니라 run 하나당 최종 당량점 부피 하나를 예측하는 방식으로 구성하였다. 실제 실험 CSV 12개를 이용한 초기 분석에서 전체 MAE는 2.306494 mL, 상대오차 MAE는 8.810450%였고, 강산-강염기 조건에서는 MAE 0.344194 mL, 상대오차 1.345296%로 가장 안정적인 결과를 보였다. Android 앱은 같은 웹 UI를 WebView로 사용하면서 스마트폰 카메라, USB-C Mini2 온도 수집, Bluetooth Classic SPP 펌프 제어, Downloads 폴더 CSV 저장을 모바일 환경에서 수행하도록 만들었다. 두 앱 모두 센서 데이터를 분석 가능한 형태로 남기는 데 초점을 두었으며, 안전을 위해 펌프는 자동 정지하지 않고 사람이 직접 제어하도록 설계하였다.
```

- [ ] **Step 2: Sync workspace final copies**

Run:
```bash
cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-001/final.md
cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-002/final.md
```

Expected: no output.

- [ ] **Step 3: Verify synced copies and no broken math escape controls**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
paths = [
    Path('docs/report_laptop_app_development_draft.md'),
    Path('_workspace/2026-06-02-001/final.md'),
    Path('_workspace/2026-06-02-002/final.md'),
]
for path in paths:
    text = path.read_text(encoding='utf-8')
    assert '전체 MAE는 2.306494 mL' in text or '전체 평균 절대오차는 2.306494 mL' in text, path
    assert '강산-강염기 조건에서는 MAE 0.344194 mL' in text or 'MAE 0.344194 mL' in text, path
    assert '\t' not in text and '\x0c' not in text, path
print('OK report and workspace copies verified')
PY
```

Expected: `OK report and workspace copies verified`.

---

### Task 3: Verification

**Files:**
- Read: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Run targeted documentation checks**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
text = Path('docs/report_laptop_app_development_draft.md').read_text(encoding='utf-8')
checks = {
    'run-level prediction': 'run 하나당 최종 당량점 부피 하나를 예측' in text,
    '12 runs': '실제 실험 CSV 12개' in text,
    'feature leakage excluded': '정답 누수' in text,
    'overall metrics': '2.306494 mL' in text and '8.810450%' in text,
    'strong acid-base metric': '0.344194 mL' in text and '1.345296%' in text,
    'limitations': '추가 데이터와 모델 개선이 필요' in text,
}
missing = [name for name, ok in checks.items() if not ok]
if missing:
    raise SystemExit('missing: ' + ', '.join(missing))
print('OK ML report additions verified')
PY
```

Expected: `OK ML report additions verified`.

- [ ] **Step 2: Commit or record no-git state**

Run:
```bash
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git add docs/report_laptop_app_development_draft.md _workspace/2026-06-02-001/final.md _workspace/2026-06-02-002/final.md docs/superpowers/plans/2026-06-02-report-ml-equivalence-results.md
  git commit -m "Explain ML equivalence results in report

Constraint: report wording must preserve measured 12-run proof-of-concept limits
Confidence: high
Scope-risk: narrow
Tested: targeted Python report content checks
Not-tested: school-format layout"
else
  echo "NO_GIT_REPO: commit skipped"
fi
```

Expected in this workspace: `NO_GIT_REPO: commit skipped`.

## Self-Review

- Spec coverage: The plan covers reading `docs/ml_equivalence_result_detailed_summary.md`, adding methodology, data size, feature inputs/exclusions, validation design, results, limitations, and summary update.
- Placeholder scan: No `TBD`, `TODO`, or unspecified implementation steps remain.
- Type consistency: Paths and metric strings match the referenced documentation.
