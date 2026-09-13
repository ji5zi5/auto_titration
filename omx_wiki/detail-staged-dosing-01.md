---
title: "detail-staged-dosing-01"
tags: ["전람회", "상세기록"]
created: 2026-09-10T11:10:15.506Z
updated: 2026-09-10T11:10:15.506Z
sources: []
links: ["detail-staged-dosing-01.md", "detailed-library.md", "evidence-conflicts-and-current-status.md"]
category: reference
confidence: medium
schemaVersion: 1
---

# detail-staged-dosing-01

## 문서의 역할과 해석
선택형 고속→저속→펄스 단계. 기본 기능과 펌웨어 capability 계약 구별.

원문: [docs/STAGED_DOSING.md](../docs/STAGED_DOSING.md)
이하 내용은 2026-09-10 현재 파일에 있는 원문 발췌를 순서대로 보존한 것이다. 새 검증·새 실험을 주장하지 않는다. 원문 내부 상대경로는 원본 문서 위치 기준이다. 수치가 다른 문서와 충돌하면 [[evidence-conflicts-and-current-status]]를 먼저 읽는다.

목차: [[detailed-library]] / [[detail-staged-dosing-01]]

<!-- BEGIN SOURCE EXCERPT -->
# Optional staged dosing

The Windows collector keeps the established automatic path as the default:

`fast continuous -> fixed STEP pulses -> stop`

An explicitly selected optional mode adds one stage:

`fast continuous -> slow continuous -> fixed STEP pulses -> stop`

The slow stage is disabled by default so the working legacy/manual paths and
older firmware remain usable. Manual `a`/`b` control is unchanged, and firmware
`STEP` pulses are still treated as 100 full steps/s.

## Firmware capability gate and transition order

Before recording or moving the pump, an enabled slow stage requires the
read-only `V` query to return exactly `PUMP SPEED 1`. A missing or different
reply rejects the recording start with a clear unsupported-firmware error.

The host changes from fast to slow only in this order:

1. `c` / STOP is confirmed through the existing absolute guard.
2. `RATE n` returns exactly `RATE ACCEPTED n`.
3. `G <remaining milliseconds>` is acknowledged.
4. The configured dispense direction is written and acknowledged with the
   same guard duration.

There is no automatic replay of RATE or a motion command after an uncertain
transition. The external cancellation predicate is checked at the serialized
direction-write boundary, so a stop/emergency generation cannot be followed by
a stale slow-stage restart.

## Trigger behavior

- The slow onset score is lower than the pulse approach score.
- Slow onset must remain above its threshold for the configured duration.
- A score already at the pulse threshold goes directly to pulse mode; the pulse
  transition wins over slow onset.
- The existing fixed pulse settle wait remains in force.

The fixed wait is **not** a measurement or proof that chemical/sensor
equilibrium has been reached. The implementation does not adapt its wait from
measured color stability.

These generic design principles follow common titration guidance: dose rapidly
far from the target, use smaller discontinuous additions and equilibrium waits
near the endpoint, and match dosing behavior to sensor response. See Metrohm's
[Practical aspects of modern titration](https://www.metrohm.com/content/dam/metrohm/shared/documents/monographs/81085085EN.pdf)
and Mettler Toledo's
[dosing-rate troubleshooting note](https://www.mt.com/us/en/home/microsites/easyplus/support/troubleshooting/secure_content/TS_00017.html).
The project's numeric thresholds are implementation settings, not values taken
from those references.

## Time and volume accounting

- One immutable absolute monotonic deadline is captured at recording start.
  Immediately before every `G`, including the first, the host recomputes and
  floors the remaining firmware milliseconds. Baseline calibration plus
  blocking STOP, RATE, G, and acknowledgement time therefore consume the same
  session budget; a slow rearm cannot create a later host deadline.
- Conservative safety volume remains at least
  `recording_elapsed_s * maximum_pump_rate_ml_per_s`, including baseline time.
  A stage change never resets this bound to a smaller value.
- CSV nominal volume is accumulated piecewise for each motor-active continuous
  segment. Each segment begins at the serialized direction-byte write timestamp,
  not after its acknowledgement. Idle/settling and pre-direction RATE/G time
  contribute zero volume.
- Slow nominal flow is recorded as
  `fast_rate_ml_per_s * slow_rate_steps_per_s / 100`. It is explicitly labeled
  uncalibrated and must not be presented as direct flow measurement.
- Pulse active time is always `steps / 100`, independent of the previous slow
  rate. Pulse nominal volume remains `steps * nominal_ml_per_step`.

Relevant CSV audit fields include `pump_dosing_stage`,
`pump_nominal_rate_ml_per_s`, `pump_rate_basis`,
`auto_stop_slow_stage_enabled`, `auto_stop_slow_rate_steps_per_s`, and
`auto_stop_slow_nominal_rate_ml_per_s`.

## Deployment and dry-verification checklist

1. Compile the firmware without uploading:
   `arduino-cli compile auto_titrator/arduino_stepper`.
2. When deployment is approved, upload the matching board build with Arduino
   CLI or Arduino IDE. Uploading changes the connected controller and is not
   performed by the host test suite.
3. Fully stop and restart the Windows collector after upload. Capability
   detection occurs when the serial connection is opened; an already-running
   collector must not be assumed to have refreshed firmware capabilities.
4. With the motor mechanically disconnected or otherwise made non-actuating,
   query `Q` and confirm the existing acknowledged v2 identity, then query `V`
   and require the exact reply `PUMP SPEED 1`.
5. Confirm the UI's optional slow-stage checkbox starts unchecked. With it
   unchecked, dry-run the established fast-to-pulse configuration.
6. Enable the slow stage only for a dry protocol run. Confirm the trace is
   `STOP`, `RATE n` / `RATE ACCEPTED n`, `G remaining_ms`, then the configured
   direction acknowledgement. Confirm an invalid RATE acknowledgement and an
   exhausted deadline produce no direction write.
7. Inspect the generated CSV: baseline and settling intervals must add no
   volume; fast and slow continuous segments must accumulate piecewise; pulse
   active time must equal `steps / 100`; slow flow must be labeled nominal and
   uncalibrated.
8. Roll back without firmware changes by clearing the slow-stage checkbox and
   restarting the recording. This restores the legacy `fast -> pulse` host
   path. Older firmware remains limited to its supported legacy/manual path.

No wet-run dosing accuracy, chemical endpoint accuracy, or measured slow-flow
calibration has been established by these software-only checks.
<!-- END SOURCE EXCERPT -->

