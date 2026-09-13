---
title: "Code Map thermal 01"
tags: ["코드", "함수", "파일지도"]
created: 2026-09-10T11:13:04.794Z
updated: 2026-09-10T11:13:04.794Z
sources: []
links: ["code-and-data-atlas.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Code Map thermal 01

현재 코드의 AST 정적 색인. 함수 존재는 작동 검증과 다르다. 줄 번호·해시는 이 스냅샷 기준.
[[code-and-data-atlas]]

## [auto_titrator/official_hikmicro.py](../auto_titrator/official_hikmicro.py)
SHA256: `aeab09d556ac584c3021caee158ef2b225d68bcfeee3e86a22f654a5bff51e7a`

Official HIKMICRO Analyzer DLL bridge for Mini2 raw-to-Celsius conversion.

This module does not fit formulas and does not use Analyzer-exported CSV values
for conversion.  It wraps the official Analyzer MTlib_OL.dll call sequence that
works with Mini2 radiometric JPEG/UVC raw frames:

- MT_Create_INT(width=256, height=192, ...)
- MT_SetConfig(type=6, APP2 tag519 calibration block)
- MT_SetConfig_INT(type=1, traced Analyzer environmental/config keys)
- MT_SetConfig_INT(type=189, APP3 tag1 word 284)
- MT_SetConfig_INT(type=12, APP3 tag1/addline block)
- MT_Process_INT(type=0, point records)

The official output field at point offset +0x10 is an int32 scaled by
64 counts/°C. HIKMICRO Analyzer's exported CSV matrix is the decimal-truncated
view of this continuous Celsius value: floor(temp_c * 10) / 10.

- L48: `OfficialDllUnavailable` (class)
- L53: `SdmpEntry` (class)
- L63: `Mini2OfficialMetadata` (class)
- L93: `iter_jpeg_segments`
- L121: `parse_sdmp_ifd`
- L150: `get_sdmp_block`
- L172: `extract_zipped_json`
- L181: `radiometric_q_params`
- L209: `type1_payload`
- L213: `tag1_internal_reflected_c`
- L226: `align128`
- L230: `_addr`
- L234: `make_mt_memory_descriptor`
- L248: `MtlibRuntime` (class)
- L258: `_MtProcessPoint` (class)
- L274: `CtypesMtlibRuntime` (class)
- L376: `_as_handle`
- L384: `OfficialMtlibConverter` (class)
- L559: `analyzer_csv_truncate_0p1`
- L565: `_validate_raw_matrix`
- L572: `OfficialMtlibWorkerConverter` (class)
- L641: `_read_exact`
- L653: `worker_loop`
- L679: `_write_worker_error`

## [auto_titrator/mini2_live.py](../auto_titrator/mini2_live.py)
SHA256: `15414a7e3e2b22d83e8419d88dce315a5219ee18be28ca1d4bcf91bb8311f6da`

Live HIKMICRO Mini2 UVC raw-frame temperature pipeline.

This module is intentionally strict: a 256x192 Celsius matrix is produced only
when an explicit raw->Celsius converter is supplied. Raw uint16 frames are never
silently treated as temperatures.

- L33: `ThermalConversionUnavailable` (class)
- L37: `RawToCelsiusConverter` (class)
- L49: `Mini2RawFrameParts` (class)
- L62: `expected_raw_frame_bytes`
- L66: `extract_mini2_raw_matrix`
- L84: `extract_mini2_frame_parts`
- L113: `RawAffineCelsiusConverter` (class)
- L139: `RawLookupCelsiusConverter` (class)
- L208: `_find_celsius_column`
- L216: `load_raw_to_celsius_converter`
- L269: `_split_worker_command`
- L287: `Mini2FfmpegRawFrameReader` (class)
- L382: `Mini2TemperatureFrame` (class)
- L394: `build_temperature_frame`
- L419: `_convert_raw_matrix`
- L429: `extract_temperature_features`
- L497: `_validate_raw_matrix`
- L504: `_validate_temperature_matrix`
- L511: `_validate_matrix_roi`
- L519: `_float_or_none`
- L528: `_round_float`
- L532: `_rect_coords_yx`
- L539: `_distribution_features`
- L573: `_format_rate`
- L577: `_read_exact`

## [auto_titrator/thermal_providers.py](../auto_titrator/thermal_providers.py)
SHA256: `de158cbd11709e6ec8ccebc973ffcff21a842c07595a7cdc46b51427715fe02c`

Thermal source providers for live/replay equivalence-point analysis.

- L22: `ThermalFramePacket` (class)
- L40: `NullThermalProvider` (class)
- L61: `MatrixReplayThermalProvider` (class)
- L85: `Mini2RawTemperatureProvider` (class)
- L156: `PaletteFrameProvider` (class)


