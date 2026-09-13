# Next deterministic sensor-ranker search

- Same-12-run typewise development MAPE: **0.359791180556%**
- Prior reference: **0.775124652778%**
- Improvement: **0.415333472222 percentage points**
- Target passed: **True**
- Seeds `(42, 1729, 20260728)`: identical predictions

Each held-out run is excluded from model, scaler, covariance, and prototype fitting. Per-type configuration selection is nevertheless post-hoc on these same 12 outer-LORO development outcomes; it is neither nested selection validation nor independent external validation.
