# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a project workspace with planning artifacts (`planning/적정기.pdf`, `planning/전람회계획서.pdf`, `planning/전람회 준비물.xlsx`) and no committed source tree yet. When code is added, use the planned modular layout:

```text
auto_titrator/
  main.py
  config.yaml
  camera.py
  color_analysis.py
  thermal_camera.py
  pump_controller.py
  endpoint_detector.py
  data_logger.py
  ml_train.py
  ml_predict.py
  arduino_stepper/arduino_stepper.ino
tests/
data/
```

Keep `.omx/` as runtime metadata. Store raw/labeled experiment CSVs under `data/raw/` and `data/labeled/`; avoid committing large generated videos unless required.

## Build, Test, and Development Commands

No build system is present yet. After scaffolding, prefer these commands:

- `python -m venv .venv && source .venv/bin/activate` — create and enter a local environment.
- `pip install -r requirements.txt` — install Python dependencies.
- `python -m auto_titrator.main --config auto_titrator/config.yaml` — run the data-collection app.
- `python3 -m unittest discover -v` — run Python tests without extra test dependencies.
- `arduino-cli compile auto_titrator/arduino_stepper` — compile motor firmware when Arduino CLI is available.

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, `snake_case` functions/variables, and `PascalCase` classes. Keep hardware constants in `config.yaml`, not hard-coded in modules. Serial commands should remain uppercase and explicit, e.g. `PRIME`, `STEP n`, `STOP`. Keep modules single-purpose: camera capture, color analysis, thermal input, pump control, logging, and ML prediction should stay separated.

## Testing Guidelines

Use Python `unittest` with tests named `tests/test_*.py`. Prioritize hardware-free tests using mocked camera frames, mocked serial ports, and fixed CSV fixtures. Test calibration math, color/thermal feature extraction, endpoint estimation, and serial command formatting. For hardware behavior, record manual verification notes with date, setup, calibration value, and observed output.

## Commit & Pull Request Guidelines

No local git history is available, so use concise decision-focused commits. Follow the repository Lore style when committing:

```text
Explain why the change was made

Tested: python3 -m unittest discover -v
Not-tested: hardware run
Confidence: medium
```

Pull requests should describe the experiment goal, changed modules, test evidence, hardware assumptions, and any screenshots/CSV samples relevant to camera or thermal analysis.

## Safety & Configuration Tips

Treat acids, bases, motors, and heated/IR equipment as safety-sensitive. Include maximum-volume limits, emergency-stop paths, and clear calibration notes before enabling automated pumping.
