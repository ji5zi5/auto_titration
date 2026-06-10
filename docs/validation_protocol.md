# Validation Protocol

This protocol is for the science-fair version of the smart titration assistant.
The device records evidence for estimating the chemical equivalence point; it
does not claim that color alone equals the equivalence point.

## Key terms

- **equivalence point**: stoichiometric point calculated from sample/titrant
  amount of substance, or measured by a trusted reference method.
- **endpoint**: observed indicator/color change point. It may be shifted from
  the true equivalence point, especially for weak-acid/weak-base systems.
- **neutral point**: pH 7. It is not always identical to the equivalence point,
  especially for weak acid or weak base titrations.
- **no automatic stop**: in the current implementation, camera/ML output is not
  wired to stop the pump automatically. The operator must supervise the pump;
  Serial Monitor key `c` stops the current simple firmware.

## Four-type validation matrix

| Titration type | Example pair | Expected challenge | Required record |
| --- | --- | --- | --- |
| `strong_acid_strong_base` | HCl + NaOH | Sharp pH change; color endpoint should be close to equivalence point. | Theoretical equivalence volume, observed endpoint, reference volume. |
| `weak_acid_strong_base` | CH3COOH + NaOH | Endpoint can shift with indicator choice; thermal/color features may help. | Ka if known, indicator, reference equivalence point. |
| `strong_acid_weak_base` | HCl + NH3(aq) | Endpoint can be less sharp; overshoot risk increases. | Kb if known, slow pump rate near expected volume. |
| `weak_acid_weak_base` | CH3COOH + NH3(aq) | Weakest endpoint signal; do not overclaim accuracy. | Repeat trials, reference method, explicit uncertainty. |

Each type should have at least three repeated runs before comparing average
color endpoint error and ML prediction error.

## Data collection checklist

1. Record raw runs from the Windows dashboard only after visible and thermal ROIs
   are locked.
2. Keep raw CSVs unchanged in `data/raw/`.
3. Copy selected runs to `data/labeled/` before adding post-run reference values.
4. Fill `reference_equivalence_volume_ml` from the theoretical calculation,
   UV-vis comparison, or another trusted reference method.
5. Fill `observed_color_endpoint_volume_ml` from video/color-curve review when
   comparing color endpoint error against ML error.
6. Do not use per-frame manual status labels. The current schema trains on
   sensor, pump-timeline, chemistry, synchronization, and derived trend features.
7. Train only after reference values exist; sparse-data warnings must be
   reported.
8. Use `auto_titrator.evaluation` to compare color endpoint vs ML prediction.

## First hardware rehearsal

Run this with water before acid/base:

1. Clamp syringe, hose, flask, visible camera, and Mini2 so the geometry stays
   fixed.
2. Prime the syringe/hose and remove bubbles.
3. Keep the hose tip above the solution surface; do not submerge it.
4. Confirm Arduino Serial Monitor keys: `a` left/reverse, `b` right/forward,
   and `c` stop.
5. Calibrate the syringe pump with measured water volume and record the measured
   `flow_rate_ml_per_s`.
6. Start the dashboard, lock visible and thermal ROIs, record a short CSV, then
   confirm injected volume, color features, thermal features, and sync offset are
   present.

## Mini2 validation note

HIKMICRO Mini2 palette/video frames are not calibrated temperature matrices.
Use `usb_palette_uncalibrated` only as a visual/diagnostic source and never
present palette RGB values as degrees Celsius.  For live calibrated thermal
features, use the official Analyzer `MTlib_OL.dll` worker path: UVC 256x344 raw
frame -> upper 256x192 raw matrix + addline block -> official DLL output
float Celsius matrix.  Approximate affine/lookup converters are validation-only
fallbacks and must not be reported as the official temperature conversion.

## Pump and chemical safety checklist

- Wear PPE: goggles, gloves, and lab coat/apron.
- Clamp the syringe, hose, and flask so the hose tip cannot fall into solution.
- Prime with water first; remove bubbles before acid/base runs.
- Enforce maximum volume in software and by operator supervision.
- Keep the motor driver power supply separate from the Arduino 5 V pin.
- Confirm `a`/`b` movement and `c` stop before real reagent use.
- Keep absorbent material and neutralization procedure available for spills.
- Never leave the syringe pump running unattended.
- Record date, reagent concentration, calibration `flow_rate_ml_per_s`, and operator.

## Live status / final result record

For every run, save or copy the final result summary with these fields:

| Field | Meaning |
| --- | --- |
| `estimated_equivalence_time_s` | Time selected by retrospective analysis. |
| `estimated_equivalence_volume_ml` | Injected volume at the selected time. |
| `equivalence_confidence` | Confidence score from color/thermal/status evidence. |
| `absolute_volume_error_ml` | Difference from theoretical or reference equivalence volume. |
| `source_quality` / `warnings` | Whether thermal data was calibrated, palette-only, or unavailable. |

Record Mini2 mode for every run:

| Mini2 mode | How to report it |
| --- | --- |
| `thermal_unavailable` | Color-only analysis; lower confidence warning required. |
| `usb_palette_uncalibrated` | Thermal palette image only; do not claim degrees Celsius. |
| `hikmicro_matrix_replay` | Calibrated exported/replayed matrix used for ROI temperature features. |
| `live_color_plus_calibrated_thermal` | Use only after live raw-to-Celsius path is verified on the device. |
