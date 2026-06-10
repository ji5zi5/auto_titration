# ML Feature Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for implementation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ML-ready derived values that capture temporal change, baseline shift, chemistry context, and data quality for titration endpoint/equivalence learning.

**Architecture:** Keep raw sensor extraction unchanged. Add a small `auto_titrator.ml_features` module that derives scalar CSV features from the current row plus recent rows. Integrate it in live Windows collection and offline collection, then expose the new columns in the versioned schema and default ML feature list.

**Tech Stack:** Python 3, `unittest`, existing CSV schema, no new dependencies.

---

### Task 1: Derived feature unit

**Files:**
- Create: `auto_titrator/ml_features.py`
- Test: `tests/test_ml_features.py`

- [ ] Write failing tests for baseline deltas, rolling window means/maxima, slopes, titration-type one-hot encoding, and sync quality values.
- [ ] Implement a pure function `derive_ml_features(history_rows, current_row, window_s=1.0, baseline_s=2.0)`.
- [ ] Run targeted tests.

### Task 2: CSV schema and defaults

**Files:**
- Modify: `auto_titrator/data_schema.py`
- Modify: `auto_titrator/ml_train.py`
- Test: `tests/test_data_schema.py`, `tests/test_ml_train_predict.py`

- [ ] Add schema columns for derived ML features and units.
- [ ] Add useful derived columns to `DEFAULT_FEATURE_COLUMNS` while keeping target/leak columns excluded.
- [ ] Run targeted tests.

### Task 3: Collection integration

**Files:**
- Modify: `tools/windows_live_collect.py`
- Modify: `auto_titrator/collection.py`
- Test: `tests/test_windows_live_collect.py`, `tests/test_collection.py`

- [ ] Stamp derived ML features into rows before CSV recording.
- [ ] Preserve existing raw/visible/thermal columns.
- [ ] Run targeted tests.

### Task 4: Documentation and sync

**Files:**
- Modify: `README.md`
- Optionally modify: `planning/scientific_calculation_policy.txt`

- [ ] Document that CSV includes temporal/baseline/quality ML features.
- [ ] Sync changed files to the Windows Downloads mirror.
- [ ] Run full test suite and syntax checks.
