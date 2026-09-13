---
title: "Code Map capture-and-ui 01"
tags: ["코드", "함수", "파일지도"]
created: 2026-09-10T11:13:04.098Z
updated: 2026-09-10T11:13:04.098Z
sources: []
links: ["code-and-data-atlas.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Code Map capture-and-ui 01

현재 코드의 AST 정적 색인. 함수 존재는 작동 검증과 다르다. 줄 번호·해시는 이 스냅샷 기준.
[[code-and-data-atlas]]

## [tools/windows_live_collect.py](../tools/windows_live_collect.py)
SHA256: `647fc164b9fa600f7e04dcc2e03028cebe573b6ea41ba46325300ca23f0e9a2f`

Windows-native Mini2 + visible-camera live feature collector.

This is the production path for the science-fair demo when Mini2 must run at
25 fps.  WSL/usbipd is useful for development, but the Mini2 raw UVC stream was
measured at ~9 fps there; Windows OpenCV reaches ~25 fps.

Example:

    py -3 tools\windows_live_collect.py --frames 250 --mini2-index 0 --visible-index 1

The output CSV contains scalar features only.  Full 256x192 temperature
matrices remain in memory unless optional debug snapshots are requested.

- L188: `CollectorInstanceLock` (class)
- L308: `PredictionReadiness` (class)
- L319: `evaluate_prediction_readiness`
- L386: `Mini2PartsReader` (class)
- L393: `CapturedMini2Frame` (class)
- L401: `TimestampedVisibleFrame` (class)
- L413: `RoiAnchor` (class)
- L420: `RoiMask` (class)
- L446: `RoiDetectionResult` (class)
- L454: `AutoRoiSettingsSnapshot` (class)
- L492: `AutoRoiWorkerResult` (class)
- L512: `RoiSelectionState` (class)
- L952: `LiveStreamState` (class)
- L1073: `_repo_relative_path`
- L1081: `csv_fieldnames_for_rows`
- L1087: `_finite_float_or_none`
- L1097: `_truthy`
- L1105: `_strict_optional_bool`
- L1114: `_strict_optional_int`
- L1127: `_strict_optional_number`
- L1141: `start_payload_experiment_metadata`
- L1157: `sanitize_csv_metadata_text`
- L1169: `build_constants_lookup_payload`
- L1196: `_equivalence_window_label`
- L1209: `_concentration_from_titrant_volume`
- L1240: `_concentration_error_percent`
- L1248: `_context_value`
- L1258: `_predicted_concentration_fields_from_row`
- L1276: `_predicted_result_fields_from_row`
- L1311: `_theoretical_equivalence_volume_from_metadata`
- L1333: `_theoretical_titration_fields_from_metadata`
- L1381: `build_pump_timeline_fields`
- L1465: `LiveCsvBuffer` (class)
- L2169: `EndpointPulseRuntime` (class)
- L2591: `LiveControlState` (class)
- L2676: `LiveStreamServerHandle` (class)
- L2689: `PulseDeliveryUncertainError` (class)
- L2693: `_serial_response_line`
- L2705: `_best_effort_serial_stop`
- L2717: `_wait_for_step_completion`
- L2747: `_wait_for_legacy_pump_ack`
- L2780: `start_guarded_continuous_at_rate`
- L2821: `ArduinoAbcPumpSerialBridge` (class)
- L3024: `resolve_pump_serial_port`
- L3053: `_validated_step_serial_command`
- L3065: `_rate_steps_per_second`
- L3077: `_pump_serial_error_likely_busy`
- L3094: `_pump_serial_user_message`
- L3118: `AutoReconnectArduinoAbcPumpSerialBridge` (class)
- L3625: `build_pump_serial_bridge_from_args`
- L3665: `LiveStreamPublisher` (class)
- L3717: `LiveJpegStreamPublisher` (class)
- L3794: `StopIntentCoordinator` (class)
- L3875: `LiveStreamHandler` (class)
- L5168: `start_live_stream_server`
- L5233: `VisibleFrameBuffer` (class)
- L5267: `Mini2CaptureThread` (class)
- L5522: `start_mini2_capture_thread`
- L5549: `VisibleLatestFrameThread` (class)
- L5660: `VisiblePreviewStreamThread` (class)
- L5713: `WindowsMini2OpenCvRawCapture` (class)
- L5756: `mini2_backend_candidates`
- L5763: `open_mini2_capture`
- L5811: `open_visible_camera`
- L5864: `opencv_backend_value`
- L5878: `mini2_raw_bytes_from_opencv_frame`
- L5904: `parse_roi`
- L5911: `resolve_visible_roi`
- L5922: `_shape_hw`
- L5933: `clamp_roi_to_shape`
- L5942: `seed_center_roi`
- L5955: `_bbox_from_mask`
- L5966: `roi_mask_from_bool`
- L5998: `keep_largest_mask_component`
- L6033: `keep_mask_component_containing`
- L6077: `_dilate_mask`
- L6087: `_erode_mask`
- L6097: `smooth_mask_shape`
- L6108: `_as_numpy_array`
- L6122: `_resize_mask_nearest`
- L6131: `scale_mask_to_shape`
- L6150: `parse_yolo_classes`
- L6163: `load_yolo_model`
- L6177: `_yolo_class_name`
- L6185: `_box_to_roi`
- L6195: `_visible_candidate_is_oversized`
- L6210: `auto_detect_visible_roi_yolo`
- L6310: `YoloVisibleRoiWorker` (class)
- L6424: `AutoRoiWorker` (class)
- L6584: `detect_visible_roi_from_seed`
- L6593: `_rect_mask_for_roi`
- L6608: `detect_visible_mask_from_seed`
- L6662: `detect_thermal_roi_from_seed`
- L6671: `detect_thermal_mask_from_seed`
- L6726: `auto_detect_visible_roi_setup_candidate`
- L6765: `auto_detect_thermal_roi`
- L6799: `parse_roi_click_payload`
- L6817: `parse_roi_rect_payload`
- L6837: `parse_roi_polygon_payload`
- L6874: `polygon_mask_from_points`
- L6906: `_repeat_mask_op`
- L6913: `_local_boundary_score`
- L6934: `_refine_visible_lasso_by_rgb_hsv_context`
- L7012: `refine_lasso_mask_to_local_boundary`
- L7090: `apply_roi_click`
- L7120: `map_visible_roi_to_thermal`
- L7168: `process_pending_roi_clicks`
- L7206: `apply_auto_roi_detection_results`
- L7244: `auto_roi_result_is_current`
- L7265: `apply_auto_roi_worker_result`
- L7295: `maybe_auto_update_rois`
- L7349: `apply_setup_auto_candidate_rois`
- L7388: `validate_matrix_roi`
- L7399: `_cached_rect_coords_yx`
- L7408: `_rect_coords_yx`
- L7414: `_distribution_features`
- L7484: `_official_celsius_output_status`
- L7497: `_add_celsius_fallback_warning`
- L7507: `_add_converter_exception_warning`
- L7517: `extract_roi_only_thermal_features`
- L7607: `_mask_metadata`
- L7622: `extract_mask_color_features`
- L7664: `extract_roi_mask_thermal_features`
- L7746: `extract_raw_thermal_features`
- L7797: `extract_raw_mask_thermal_features`
- L7843: `default_dll_dir`
- L7850: `default_metadata_jpeg`
- L7854: `build_official_converter`
- L7865: `orient_thermal_matrix`
- L7880: `orient_mini2_frame_parts`
- L7889: `unavailable_thermal_features`
- L7903: `build_sync_metadata`
- L7939: `summarize_sync`
- L7961: `load_live_prediction_model`
- L7984: `load_typewise_live_prediction_model`
- L7995: `load_endpoint_prediction_model`
- L8010: `finish_live_automatic_stop`
- L8124: `run`
- L9261: `write_rows`
- L9271: `rgb_bmp_bytes`
- L9306: `jpeg_bytes`
- L9326: `write_rgb_bmp`
- L9332: `write_live_bytes`
- L9366: `_json_float`
- L9376: `raw_matrix_to_rgb_preview`
- L9400: `roi_to_string`
- L9406: `draw_roi_overlay`
- L9430: `draw_mask_overlay`
- L9468: `build_visible_stream_frame`
- L9478: `build_thermal_stream_frame`
- L9489: `build_live_payload`
- L9825: `write_live_preview`
- L9869: `main`

## [tools/dashboard_server.py](../tools/dashboard_server.py)
SHA256: `90c24b7813b6bfac5a8b52d4fa2be2e3bee4a2f65e5e16eb9733cbb8676be0e9`

Local web dashboard server for the science-fair titration app.

The static website can be opened with a plain http.server, but this small
stdlib-only server adds read-only JSON endpoints for the latest collected CSV so
that the dashboard can poll live feature rows during a demonstration.

- L36: `ServerConfig` (class)
- L43: `_placeholder_bmp_bytes`
- L81: `ensure_live_preview_placeholders`
- L130: `_json_response`
- L140: `safe_repo_path`
- L164: `read_csv_tail`
- L202: `list_csv_files`
- L216: `DashboardHandler` (class)
- L474: `build_server`
- L492: `main`

## [auto_titrator/camera.py](../auto_titrator/camera.py)
SHA256: `c1625595fa341d6950bfb8375a69ff1f530bd4835d62b8faee68754ca1fedbe3`

USB camera capture wrappers.

OpenCV is imported lazily so the analysis modules remain testable without
camera dependencies installed.

- L15: `CameraConfig` (class)
- L23: `UsbCamera` (class)

## [auto_titrator/color_analysis.py](../auto_titrator/color_analysis.py)
SHA256: `0363a7b8faa0d4c5dd28d7e9b7a04e1b3bb13c47f5d169c56be0adcb4ced99bf`

Color feature extraction for visible and thermal-palette camera frames.

- L18: `Roi` (class)
- L40: `rgb_to_hsv`
- L81: `ColorFeatureExtractor` (class)
- L142: `prefix_features`

## [auto_titrator/feature_history.py](../auto_titrator/feature_history.py)
SHA256: `2b06aed4760f2bba1b0b18015f267cc8861100c0803bc23072ad8209cfbfce2a`

Lightweight feature history for live equivalence-point analysis.

This module deliberately stores scalar features, labels, confidence, and source
metadata. Full camera frames or thermal matrices are not serialized by default;
they belong in provider/display code, not in the feature history artifact.

- L21: `FeatureSample` (class)
- L52: `FeatureHistory` (class)
- L89: `_as_scalar`

## [auto_titrator/data_logger.py](../auto_titrator/data_logger.py)
SHA256: `fef44df47463a1b555023c7095bdb3a581d0171d78ba06e85553810535040056`

CSV logging for synchronized titration camera features.

- L12: `CsvDataLogger` (class)

## [auto_titrator/data_schema.py](../auto_titrator/data_schema.py)
SHA256: `f45c85896fa6f0647b42aeedb3b1d1a5ae8a1da7c7b267dffe6a27c6d7a8a23b`

Versioned CSV schema for titration data collection.




