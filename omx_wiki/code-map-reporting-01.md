---
title: "Code Map reporting 01"
tags: ["코드", "함수", "파일지도"]
created: 2026-09-10T11:13:05.843Z
updated: 2026-09-10T11:13:05.843Z
sources: []
links: ["code-and-data-atlas.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Code Map reporting 01

현재 코드의 AST 정적 색인. 함수 존재는 작동 검증과 다르다. 줄 번호·해시는 이 스냅샷 기준.
[[code-and-data-atlas]]

## [tools/build_national_report_hwpx.py](../tools/build_national_report_hwpx.py)
SHA256: `c63fb0ab220b32dbffbc74160804ecd37975f02b4548867e0f9d70b62309cf0d`

Build a reviewable HWPX draft from the national science-fair Markdown report.

The builder intentionally uses only Python's standard library plus Pillow, which
is already used by the repository's report-asset tooling.  It reuses Form 6 from
the official 2026 National Science Fair forms and embeds every real image that is
already referenced by the Markdown.  Missing identity fields and three evidence
screenshots remain explicit placeholders; the script never fabricates them.

The result is an *automatic review draft*.  Hancom Office must still open and
save it once so line layout, page numbers, the table of contents, and the final
30-page limit can be checked in the official renderer.

- L90: `EmbeddedImage` (class)
- L99: `_xml_bytes`
- L103: `_plain_text`
- L114: `_new_paragraph`
- L139: `_set_paragraph_text`
- L163: `_find_table`
- L170: `_fill_cover`
- L197: `_add_body_bold_style`
- L215: `_make_section_properties`
- L240: `_parse_markdown_tables`
- L252: `_column_widths`
- L264: `_new_table`
- L368: `_media_type`
- L379: `_new_picture`
- L475: `_extract_image_sources`
- L486: `_prepare_images`
- L505: `_markdown_to_section`
- L596: `_update_content_manifest`
- L651: `_preview_image`
- L673: `build_hwpx`
- L741: `validate_hwpx`
- L822: `_parse_args`
- L839: `main`

## [tools/analyze_existing_data_report_evidence.py](../tools/analyze_existing_data_report_evidence.py)
SHA256: `1cb6cabc5c475b672da9d6a4aa172546612ee6710f1fddfc9604d52921c6ede0`

Build a deterministic evidence report from the already-collected titration data.

This tool does not train models or alter source CSVs.  It audits the twelve raw
runs and recomputes descriptive/error statistics from stored prediction files.

- L132: `read_csv`
- L137: `sha256_file`
- L145: `finite_float`
- L153: `run_id_from_row`
- L158: `reported_indicator_correction`
- L167: `inventory_raw_runs`
- L210: `is_invalid_all_zero_thermal_summary`
- L225: `scaled_mad`
- L232: `_thermal_contrast_for_window`
- L322: `thermal_snr_for_run`
- L342: `thermal_sensitivity_rows`
- L375: `prediction_rows`
- L395: `error_metrics`
- L412: `paired_error_rows`
- L458: `linear_quantile`
- L470: `paired_bootstrap_ci`
- L484: `stratified_paired_bootstrap_ci`
- L510: `exact_sign_flip_p_value`
- L525: `exact_sign_test_p_value`
- L537: `average_ranks`
- L552: `pearson_correlation`
- L564: `spearman_correlation`
- L568: `spearman_permutation_p_value`
- L588: `csv_value`
- L598: `write_csv`
- L606: `reaction_type_summaries`
- L642: `model_stability_evidence`
- L702: `comparison_provenance`
- L732: `write_plot`
- L801: `write_thermal_plots`
- L866: `markdown_report`
- L943: `analyze`
- L1205: `build_parser`
- L1236: `main`

## [tools/pulse_replay_analysis.py](../tools/pulse_replay_analysis.py)
SHA256: `e665df05d659ffa646992d247ed7935061581c7ead84661de769eb09c7c65fcf`

Replay recorded endpoint labels under three hypothetical stop schedules.

This is deliberately a dependency-free, offline counterfactual calculation.  It
does not recreate mixing, pump mechanics, sensor response after a hypothetical
pause, or any other wet-lab behavior.

- L31: `DatasetError` (class)
- L36: `Observation` (class)
- L43: `LoadedTrace` (class)
- L52: `PolicyResult` (class)
- L63: `_normalized`
- L104: `_find_column`
- L112: `_finite_float`
- L122: `_boolean`
- L140: `load_trace`
- L213: `_confirmed_stop`
- L228: `compare_policies`
- L302: `paths_from_inventory`
- L327: `analyze_paths`
- L380: `_parser`
- L394: `main`

## [tools/benchmark_live_pipeline.py](../tools/benchmark_live_pipeline.py)
SHA256: `82be07cc41e4b2e896d5b94af3f6d3d3ac57dc0dea545f96c16c5b3f3aa5cb57`

Deterministic 25 fps evaluator for the live titration hot path.

This benchmark is hardware-free.  It proves queue/session/CSV semantics and
Python-side processing budget; the HIKMICRO DLL and physical cameras still need
the Windows hardware check reported by the collector itself.

- L36: `FixedRateMini2Reader` (class)
- L86: `VectorOfficialConverter` (class)
- L97: `visible_frame`
- L105: `verify_latest_preview`
- L137: `benchmark`
- L296: `build_parser`
- L309: `main`


