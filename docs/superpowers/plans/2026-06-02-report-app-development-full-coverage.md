# Report App Development Full Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the science-fair app development report so it explicitly covers every implemented data-collection, pump, Mini2 temperature, chemistry calculation, CSV, and Android feature found in the codebase.

**Architecture:** This is a documentation-only change. The report draft remains the primary edited artifact, and the active Humanize Korean final artifact is synchronized after editing. Verification is text-based: grep for required feature names and guard against vague “등” summaries in the CSV-value sections.

**Tech Stack:** Markdown report text, local repository evidence from Python/Android source files, shell grep verification.

---

## File Structure

- Modify: `docs/report_laptop_app_development_draft.md`
  - Responsibility: Main Korean report draft for laptop and Android app development sections.
- Modify: `_workspace/2026-06-02-001/final.md`
  - Responsibility: Previously exported final report artifact; must match the updated draft.
- Modify: `_workspace/2026-06-02-002/final.md`
  - Responsibility: Humanize Korean follow-up artifact; must match the updated draft.
- Reference only: `auto_titrator/data_schema.py`
  - CSV schema evidence for experiment, pump, frame, visible, thermal, ML, and result fields.
- Reference only: `auto_titrator/chemistry.py`, `auto_titrator/chemical_constants.py`, `auto_titrator/indicator_models.py`
  - Chemistry, pH, IUPAC pKa, and indicator range evidence.
- Reference only: `tools/windows_live_collect.py`, `website/app.js`, `website/index.html`
  - Windows dashboard, CSV recording, pump bridge, and UI evidence.
- Reference only: `mobile/android/app/src/main/java/kr/auto/titration/mobile/...`
  - Android WebView, CameraX, Mini2, Bluetooth pump, local CSV export evidence.

### Task 1: Replace vague CSV paragraphs with explicit recorded-value groups

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Locate existing CSV/summary paragraphs**

Run:
```bash
rg -n "CSV|수집된 CSV|짧은 요약문" docs/report_laptop_app_development_draft.md
```
Expected: Show current CSV paragraphs so the replacement location is clear.

- [ ] **Step 2: Replace vague CSV text with explicit field groups**

Edit the laptop app section so it names the recorded field groups and values:

```markdown
CSV에는 실험 조건값으로 `schema_version`, `experiment_id`, `titration_type`, `sample_name`, `sample_concentration_M`, `sample_volume_ml`, `sample_valence`, `titrant_name`, `titrant_concentration_M`, `titrant_valence`, `Ka`, `Kb`, `indicator`, `chemistry_model`, `chemistry_model_version`를 저장하였다.

화학 상수와 지시약 관련 값은 `constants_source`, `constants_source_id`, `constants_query`, `constants_candidate_count`, `constants_lookup_ambiguous`, `constants_confirmation_status`, `constants_warning`, `selected_pka_type`, `selected_pka_value`, `selected_pka_temperature_c`, `activity_model`, `ionic_strength_m`, `ionic_strength_label`, `activity_warning`, `theoretical_equivalence_pH`, `selected_equivalence_step`, `indicator_transition_low_pH`, `indicator_transition_high_pH`, `indicator_endpoint_volume_ml`, `indicator_endpoint_offset_ml`, `indicator_endpoint_confidence`, `indicator_endpoint_warning`, `standard_solution_uncertainty_note`로 나누어 기록하였다.
```

- [ ] **Step 3: Add explicit pump/frame/visible/thermal/ML/result field groups**

Add paragraphs that explicitly include:

```markdown
펌프와 주입량 값은 `pump_mode`, `pump_state`, `pump_step_count`, `pump_commanded_step_count`, `pump_confirmed_step_count`, `pump_elapsed_s`, `pump_run_rate_ml_per_s`, `pump_calibrated_ml_per_step`, `pump_calibrated_steps_per_ml`, `commanded_volume_ml`, `confirmed_injected_volume_ml`, `injected_volume_ml`, `distance_to_equivalence_ml`, `time_to_equivalence_s`, `theoretical_equivalence_time_s`, `equivalence_window_ml`, `equivalence_window_label`로 저장하였다.

시간 동기화 값은 `csv_session_id`, `csv_row_index`, `csv_recording_started_epoch_s`, `csv_recording_elapsed_s`, `csv_mark_sequence`, `csv_event_note`, `time_s`, `frame_id`, `thermal_time_s`, `visible_time_s`, `sync_offset_ms`, `sync_method`, `sync_quality`, `sync_warning`으로 저장하였다.

일반 카메라 색상 값은 `visible_R_mean`, `visible_G_mean`, `visible_B_mean`, `visible_H_mean`, `visible_S_mean`, `visible_V_mean`, `visible_H_delta`, `visible_S_delta`, `visible_V_delta`, `visible_HSV_delta`, `visible_color_delta`로 저장하였다.
```

- [ ] **Step 4: Verify field names exist in draft**

Run:
```bash
rg -n "sample_concentration_M|theoretical_equivalence_pH|pump_confirmed_step_count|sync_offset_ms|visible_HSV_delta|thermal_raw_roi_p95|training_quality_score|estimated_equivalence_volume_ml" docs/report_laptop_app_development_draft.md
```
Expected: All required fields are found.

### Task 2: Add chemistry concentration, equivalence, pH, IUPAC, and indicator explanation

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Add stoichiometry paragraph**

Insert after the experiment/CSV condition explanation:

```markdown
농도 계산 기능도 포함하였다. 앱은 시료 농도, 시료 부피, 시료 가수, 표준용액 농도, 표준용액 가수를 입력받고 `시료 농도 × 시료 부피 × 시료 가수 / (표준용액 농도 × 표준용액 가수)`의 당량 관계로 이론 당량점 부피를 계산한다. 실험 후에는 측정된 당량점 부피를 반대로 대입하여 미지 시료 농도 또는 미지 표준용액 농도를 계산할 수 있게 하였다.
```

- [ ] **Step 2: Add pH model paragraph**

Insert immediately after Step 1:

```markdown
pH 계산은 적정 종류에 따라 다르게 처리하였다. 강산-강염기 적정은 당량점 pH를 7.0으로 두고, 약산-강염기 적정은 약산의 pKa와 물의 이온곱을 이용해 짝염기의 가수분해를 계산하였다. 강산-약염기 적정은 약염기의 pKb를 이용해 짝산의 영향을 반영하였다. 약산-약염기 적정은 pKa와 pKb 차이를 이용해 당량점 pH를 참고값으로 계산하였다. 이 계산 결과는 `theoretical_equivalence_pH`, `selected_pka_value`, `selected_pka_type`, `ionic_strength_m`, `activity_model`, `activity_warning`에 기록된다.
```

- [ ] **Step 3: Add IUPAC and indicator paragraph**

Insert immediately after Step 2:

```markdown
pKa 값은 사용자가 직접 입력할 수도 있고, 앱에 포함된 IUPAC Dissociation Constants high-confidence CSV에서 물질명을 검색해 후보를 고를 수도 있게 하였다. 검색 결과는 후보 개수, 모호성 여부, 선택된 pKa 종류, pKa 값, 측정 온도와 함께 저장된다. 지시약은 페놀프탈레인, 메틸오렌지, BTB의 변색 범위를 기록하며, 변색 범위는 각각 pH 8.2–10.0, pH 3.1–4.4, pH 6.0–7.6으로 관리하였다.
```

- [ ] **Step 4: Verify chemistry terms**

Run:
```bash
rg -n "농도 계산|미지 시료 농도|당량점 pH|IUPAC|페놀프탈레인|메틸오렌지|BTB" docs/report_laptop_app_development_draft.md
```
Expected: All terms appear.

### Task 3: Expand Arduino pump and Mini2 temperature analysis sections

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Expand Arduino pump paragraph**

Replace the current pump paragraph with text that includes exact commands:

```markdown
시린지 펌프는 아두이노와 직접 연결하였다. 아두이노는 STEP, DIR, ENABLE 핀으로 스테퍼 모터 드라이버를 제어하고, 노트북 앱은 USB 시리얼 통신으로 아두이노에 명령을 보낸다. 현재 펌프 펌웨어는 `a`, `b`, `c` 명령을 사용한다. `a`는 되감기 방향, `b`는 원래 주입 방향, `c`는 정지 명령이다. 노트북 앱의 “녹화 시작”은 `b` 명령과 연결되고, “녹화 종료”는 `c` 명령과 연결되며, 별도 버튼으로 `a` 명령을 보내 시린지를 뒤로 당길 수 있다.
```

- [ ] **Step 2: Expand Mini2 raw and Celsius paragraphs**

Add text that explicitly names raw and temperature statistics:

```markdown
Mini2 열화상 카메라는 256×344 raw frame을 제공하고, 앱은 위쪽 256×192 영역을 열화상 raw 행렬로 분리하였다. 전체 raw 행렬에서는 `thermal_raw_min`, `thermal_raw_max`, `thermal_raw_mean`, `thermal_raw_std`, `thermal_raw_range`, `thermal_raw_iqr`, `thermal_raw_p05`, `thermal_raw_p25`, `thermal_raw_p50`, `thermal_raw_p75`, `thermal_raw_p95`를 계산하였다. ROI raw 영역에서는 `thermal_raw_roi_avg`, `thermal_raw_roi_max`, `thermal_raw_roi_min`, `thermal_raw_roi_std`, `thermal_raw_roi_range`, `thermal_raw_roi_iqr`, `thermal_raw_roi_p05`, `thermal_raw_roi_p25`, `thermal_raw_roi_p50`, `thermal_raw_roi_p75`, `thermal_raw_roi_p95`, `thermal_raw_roi_hot_fraction`, `thermal_raw_roi_cold_fraction`, `thermal_raw_roi_delta`, `thermal_raw_roi_min_x`, `thermal_raw_roi_min_y`, `thermal_raw_roi_max_x`, `thermal_raw_roi_max_y`를 계산하였다.

섭씨 온도값은 HIKMICRO 공식 MTlib 변환 경로를 사용해 raw 값을 온도 행렬로 바꾸는 방식으로 처리하였다. 변환된 온도 행렬에서는 `thermal_roi_avg`, `thermal_roi_max`, `thermal_roi_min`, `thermal_roi_std`, `thermal_roi_range`, `thermal_roi_iqr`, `thermal_roi_p05`, `thermal_roi_p25`, `thermal_roi_p50`, `thermal_roi_p75`, `thermal_roi_p95`, `thermal_roi_hot_fraction`, `thermal_roi_cold_fraction`, `thermal_roi_delta`, `thermal_matrix_avg`, `thermal_matrix_max`, `thermal_matrix_min`, `thermal_matrix_std`, `thermal_matrix_range`, `thermal_matrix_iqr`, `thermal_matrix_p05`, `thermal_matrix_p25`, `thermal_matrix_p50`, `thermal_matrix_p75`, `thermal_matrix_p95`를 계산하였다.
```

- [ ] **Step 3: Verify no vague thermal summary remains**

Run:
```bash
rg -n "thermal_raw_roi_hot_fraction|thermal_matrix_p95|HIKMICRO 공식 MTlib|STEP, DIR, ENABLE|`a`, `b`, `c`" docs/report_laptop_app_development_draft.md
```
Expected: All terms appear.

### Task 4: Expand Android section with phone-local CSV, Mini2 temperature collection, and Bluetooth pump

**Files:**
- Modify: `docs/report_laptop_app_development_draft.md`

- [ ] **Step 1: Add Android CameraX and CSV fields paragraph**

Insert in Android section:

```markdown
Android 앱은 CameraX ImageAnalysis로 스마트폰 기본 카메라 프레임을 받아 `visible_R_mean`, `visible_G_mean`, `visible_B_mean`, `visible_H_mean`, `visible_S_mean`, `visible_V_mean`, `visible_HSV_delta`, `visible_color_delta`를 계산한다. Android CSV에는 `schema_version`, `experiment_id`, `titration_type`, `sample_name`, `sample_concentration_M`, `sample_volume_ml`, `titrant_name`, `titrant_concentration_M`, `theoretical_equivalence_volume_ml`, `pump_mode`, `pump_state`, `time_s`, `frame_id`, `visible_time_s`, `sync_quality`, `injected_volume_ml`, `distance_to_equivalence_ml`이 들어간다.
```

- [ ] **Step 2: Add Android Mini2 thermal CSV paragraph**

Insert after Step 1:

```markdown
Android 앱에서도 USB-C Mini2에서 열화상 프레임과 온도 변화를 수집한다. 모바일 CSV에는 `thermal_source`, `thermal_roi_avg`, `thermal_roi_max`, `thermal_roi_min`, `thermal_matrix_avg`, `thermal_matrix_shape`, `thermal_raw_roi_avg`, `thermal_raw_roi_max`, `thermal_raw_roi_min`, `thermal_raw_roi_std`, `thermal_raw_roi_delta`, `thermal_raw_roi_p50`, `thermal_raw_roi_iqr`, `thermal_raw_mean`, `thermal_raw_max`, `thermal_raw_min`, `thermal_raw_std`, `thermal_conversion_model`, `thermal_calibrated`가 기록된다.
```

- [ ] **Step 3: Add Android Bluetooth pump and export paragraph**

Insert after Step 2:

```markdown
펌프는 Android에서도 블루투스로 연결할 수 있게 하였다. 앱은 Bluetooth Classic SPP 방식으로 HC-05, HC-06, Arduino, ESP32 계열 장치를 찾고, 펌프 명령은 `a`, `b`, `c`, `s`, `r` 체계로 보낸다. `a`는 역방향, `b`는 정방향, `c`는 정지, `s`는 상태 확인, `r`은 리셋이다. Android CSV에는 `pump_step_count`, `pump_confirmed_step_count`, `pump_firmware_volume_ml`, `pump_last_status`, `pump_elapsed_s`, `theoretical_equivalence_time_s`, `time_to_equivalence_s`, `equivalence_window_ml`, `equivalence_window_label`이 같이 남는다. 녹화가 끝나면 앱은 CSV를 스마트폰 Downloads 폴더에 `auto-titration-android-run-...csv` 파일로 저장한다.
```

- [ ] **Step 4: Verify Android terms**

Run:
```bash
rg -n "CameraX ImageAnalysis|USB-C Mini2|thermal_raw_roi_p50|Bluetooth Classic SPP|auto-titration-android-run" docs/report_laptop_app_development_draft.md
```
Expected: All terms appear.

### Task 5: Sync final artifacts and verify vague-summary ban

**Files:**
- Modify: `_workspace/2026-06-02-001/final.md`
- Modify: `_workspace/2026-06-02-002/final.md`

- [ ] **Step 1: Copy updated draft to final artifacts**

Run:
```bash
cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-001/final.md
cp docs/report_laptop_app_development_draft.md _workspace/2026-06-02-002/final.md
```
Expected: No output and both files updated.

- [ ] **Step 2: Verify required concepts**

Run:
```bash
rg -n "CSV에는 실험 조건값|농도 계산|pH 계산|IUPAC|시린지 펌프는 아두이노|Mini2 열화상 카메라는 256×344|Android 앱에서도 USB-C Mini2|Bluetooth Classic SPP" docs/report_laptop_app_development_draft.md _workspace/2026-06-02-001/final.md _workspace/2026-06-02-002/final.md
```
Expected: Required concepts appear in all three files.

- [ ] **Step 3: Verify the CSV sections do not hide behind vague “등” wording**

Run:
```bash
python3 - <<'PY'
from pathlib import Path
text = Path('docs/report_laptop_app_development_draft.md').read_text(encoding='utf-8')
required = [
    'sample_concentration_M', 'theoretical_equivalence_pH', 'pump_confirmed_step_count',
    'visible_HSV_delta', 'thermal_raw_roi_hot_fraction', 'thermal_matrix_p95',
    'training_quality_score', 'estimated_equivalence_volume_ml', 'Bluetooth Classic SPP',
]
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit('missing: ' + ', '.join(missing))
print('OK required report details present')
PY
```
Expected: `OK required report details present`.

## Self-Review

- Spec coverage: CSV fields, Arduino pump, Mini2 raw/temperature analysis, concentration, pH, IUPAC, indicators, Android CameraX, Android Mini2, Android Bluetooth pump, Android CSV export are all covered by tasks.
- Placeholder scan: No TBD/TODO/fill-in placeholders are present.
- Type consistency: Field names match repository evidence from `data_schema.py`, Android `CsvSchema.kt`, and bridge/session classes.
