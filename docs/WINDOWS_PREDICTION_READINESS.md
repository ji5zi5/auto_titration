# Windows final-prediction readiness

## Runtime contract

Final equivalence volume, concentration, and predicted pH are emitted only after a shared post-run engineering guard passes. The guard runs before the type-conditioned sensor ranker, legacy typewise classifier, JSON regression model, and feature-peak fallback.

`predicted_equivalence_status` has exactly four values:

- `pending` — recording/finalization has not produced a terminal decision.
- `available` — one prediction path returned a finite positive equivalence volume.
- `withheld` — the recorded observations did not pass the engineering readiness guard. No fallback is attempted and final prediction fields are omitted.
- `unavailable` — readiness passed, but every configured model/fallback failed to produce a result.

`predicted_equivalence_reason` gives a machine-readable reason, including `insufficient_usable_sensor_time_volume_observations`, `insufficient_recording_time_span`, `insufficient_recorded_volume_progression`, `flat_recorded_sensor_signals`, and the successful model/fallback reason.

The live/status payload carries both fields. It also carries `csv_recording_started_epoch_s` from the CSV session status so clients can deduplicate GET and SSE terminal notifications for the same recording.

## Engineering guard, not chemical proof

A run is eligible to *attempt* final prediction only when it has:

1. at least 8 usable observations;
2. finite, non-negative `time_s` and `injected_volume_ml` on each usable observation;
3. one complete sensor group on each usable observation: RGB, HSV, calibrated thermal average/min/max, or raw thermal p50/p95;
4. at least 3.0 seconds of recorded time progression;
5. positive recorded volume progression; and
6. at least one non-flat signal among the accepted sensor columns.

These thresholds prevent obviously truncated, static, or malformed CSVs from claiming a final concentration. They are an engineering plausibility guard only: passing does **not** prove that a chemical endpoint occurred or that a prediction is scientifically valid.

Neither theoretical equivalence volume nor the typed/unknown sample concentration participates in eligibility. They cannot make a short or sensorless run prediction-ready. Raw feature observations remain in the exported CSV when prediction is withheld; only unready final-prediction annotations are cleared and replaced by the explicit terminal status/reason.

## Selective Windows integration

The Windows checkout inspected at `/mnt/c/Users/Jio/Downloads/auto_titration` still had the legacy typewise model and loader, but lacked the intended final endpoint loader and artifact. Do not silently replace the legacy model and do not retrain. The final post-run ranker and the causal auto-stop classifier have different responsibilities and must retain explicitly selected paths.

Required files for the intended final post-run model:

| File | SHA-256 |
| --- | --- |
| `auto_titrator/type_conditioned_sensor_live_model.py` | `22b9bbbb71b8a11ef1ac12f928a516f3d07bbd29b563a7ddb1512c0b5af79ce4` |
| `tools/sensor_transition_candidate_union.py` | `51c7f3399827cf5f80049ca1ae42d1a924d15a00da25b877ea4438e83fe42efa` |
| `data/labeled/type-conditioned-sensor-endpoint-ranker.pkl` | `378a19b3aead649bfe783b42518792001c3de33aebcb51bcecd47d60067e3f90` |

Trusted local runtime dependencies are Python, NumPy, and scikit-learn plus the Python standard library. The frozen pickle references scikit-learn PLS, linear-discriminant, kernel-ridge, pipeline, and preprocessing classes. XGBoost, LightGBM, and CatBoost are research-only and are not required to load or predict with this artifact.

The files staged under Windows `.runtime/site-fix-validation/` matched the hashes above. Native Windows Python 3.14.3 / NumPy 2.4.4 / scikit-learn 1.9.0 and WSL scikit-learn 1.8.0 produced exactly equal six-decimal predicted volumes for all 12 original CSV runs (`windows.json` versus `wsl.json`). Windows emitted `InconsistentVersionWarning`; therefore scikit-learn 1.9.0 is a tested compatibility boundary for this comparison, not proof of general cross-version pickle compatibility. No package change is justified by this evidence.

All 12 original validation CSVs pass the readiness guard (120–261 usable observations, 28.184–56.513 seconds, and 27.897–55.944 mL recorded progression). Wiring should point the final endpoint option to the intended artifact while leaving the existing legacy typewise/causal selections explicit.
