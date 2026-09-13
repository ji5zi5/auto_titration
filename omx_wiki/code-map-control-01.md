---
title: "Code Map control 01"
tags: ["코드", "함수", "파일지도"]
created: 2026-09-10T11:13:05.144Z
updated: 2026-09-10T11:13:05.144Z
sources: []
links: ["code-and-data-atlas.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Code Map control 01

현재 코드의 AST 정적 색인. 함수 존재는 작동 검증과 다르다. 줄 번호·해시는 이 스냅샷 기준.
[[code-and-data-atlas]]

## [auto_titrator/auto_stop.py](../auto_titrator/auto_stop.py)
SHA256: `6fa313c743fa592a6157abf25f85a0099a3b98e27453b77bf01c78f317f6d84b`

Opt-in pump auto-stop based on a model-confirmed visible-ROI color change.

The detector deliberately does not use a theoretical equivalence volume.  It
learns the starting color from the first second of the live run, ignores short
color flashes, and starts its delay only when the causal live classifier also
reports an endpoint-like frame.  Injected volume is used by the trained live
classifier, for audit output, and for the independent physical maximum-volume
safety limit; the run's theoretical equivalence volume is never a stop gate.

- L41: `_finite_float`
- L49: `_first_finite`
- L57: `_visible_color_vector`
- L71: `_configure_single_row_model_inference`
- L93: `_color_distance`
- L115: `AbsolutePumpSafetyGuard` (class)
- L587: `AutoStopDecision` (class)
- L632: `PersistentColorAutoStopDetector` (class)
- L884: `ColorChangeAutoStopController` (class)

## [auto_titrator/pulse_control.py](../auto_titrator/pulse_control.py)
SHA256: `a03999771d423cbbef2fd68bea3c1db5eee2ee36cd8a1a1a7bd354076463d591`

Pure endpoint-near pulse-control state machine.

This module emits command *intents* only.  It does not send serial commands,
estimate delivered volume, or claim that a pulse has completed.  Callers must
provide monotonic timestamps, a conservative measured/commanded volume, and an
explicit pulse-completion event from their eventual hardware integration.

- L30: `PulseState` (class)
- L39: `PulseControlConfig` (class)
- L114: `CommandIntent` (class)
- L131: `PulseObservation` (class)
- L146: `PulseTransition` (class)
- L153: `PulseController` (class)
- L319: `simulate_trace`
- L334: `_is_finite_number`

## [auto_titrator/pump_controller.py](../auto_titrator/pump_controller.py)
SHA256: `4a2e1934e1405a3195a332839a407bed710f61f0592e71468856621dfc57863f`

Manual syringe-pump command controller with dry-run support and safety checks.

- L24: `validate_direction`
- L31: `validate_firmware_float_range`
- L49: `validate_firmware_int_range`
- L61: `validate_ml_per_step`
- L70: `validate_steps_per_ml`
- L79: `validate_step_command_count`
- L83: `validate_max_total_steps`
- L88: `validate_max_volume_ml`
- L93: `validate_calibrated_max_volume_ml`
- L116: `min_run_rate_for_step_interval`
- L122: `validate_run_rate_ml_per_s`
- L137: `format_firmware_float`
- L147: `Transport` (class)
- L153: `DryRunTransport` (class)
- L166: `SerialTransport` (class)
- L191: `PumpSafetyConfig` (class)
- L202: `PumpController` (class)

## [tools/pump_calibration.py](../tools/pump_calibration.py)
SHA256: `1a70d21566a222983dcc242497ebd0e88a1ef062fe5b5b2ac97113a0f0dcae22`

Calculate syringe-pump ml/step calibration from water-dispense trials.

- L23: `format_float`
- L29: `CalibrationTrial` (class)
- L39: `CalibrationResult` (class)
- L68: `CalibrationObservation` (class)
- L131: `CalibrationStatistics` (class)
- L163: `PositionCalibrationResult` (class)
- L238: `_statistics_for`
- L264: `_linearity`
- L284: `analyze_observations`
- L325: `_optional_positive_int`
- L335: `read_observations`
- L362: `write_observation_analysis_csv`
- L405: `process_observation_csv`
- L425: `write_position_template`
- L471: `calculate_calibration`
- L507: `write_csv`
- L535: `write_summary`
- L540: `process`
- L553: `parse_args`
- L593: `main`


