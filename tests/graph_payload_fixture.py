"""Synthetic measurements serialized by the real collector; no device access."""
import json
import math
import sys

from tools.windows_live_collect import build_live_payload


def graph_payload_fixture(frame_count=81, fps=4):
    initial = {
        'session_id': 7, 'started_epoch_s': 1000.0, 'updated_epoch_s': 1000.0,
        'state': 'recording', 'recording': True, 'finalizing': False,
        'row_count': 0, 'recording_elapsed_s': 0.0,
    }
    frames = []
    for index in range(frame_count):
        elapsed = index / fps
        temperature = 24 + 2 * math.sin(index / 30)
        features = {
            'thermal_calibrated': True, 'thermal_conversion_status': 'ok',
            'thermal_roi_avg': temperature,
            'thermal_roi_min': temperature - .2, 'thermal_roi_max': temperature + .2,
        }
        row = {
            'frame_id': index, 'time_s': elapsed,
            'visible_color_delta': 2 + 30 / (1 + math.exp(-(elapsed - 10))),
            'pump_dosing_stage': 'fast' if index < 30 else 'slow_continuous' if index < 55 else 'pulse_injecting',
        }
        status = {**initial, 'updated_epoch_s': 1000.25 + elapsed,
                  'recording_elapsed_s': elapsed, 'row_count': index + 1}
        frames.append(build_live_payload(features, row, csv_status=status))
    finalizing = {**status, 'state': 'finalizing', 'recording': False,
                  'finalizing': True, 'updated_epoch_s': 1001.0 + elapsed}
    stopped = {**finalizing, 'state': 'stopped', 'finalizing': False,
               'updated_epoch_s': 1002.0 + elapsed, 'injected_volume_ml': 20.0,
               'predicted_equivalence_status': 'available',
               'predicted_equivalence_volume_ml': 19.8,
               'sample_concentration_from_predicted_equivalence_M': .099}
    return {'initial': initial, 'frames': frames,
            'finalizing': build_live_payload(features, row, csv_status=finalizing),
            'stopped': build_live_payload(features, row, csv_status=stopped)}


if __name__ == '__main__':
    print(json.dumps(graph_payload_fixture(*map(int, sys.argv[1:]))))
