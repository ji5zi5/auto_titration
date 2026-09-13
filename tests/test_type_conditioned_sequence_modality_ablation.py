import copy
import unittest

from tools import sensor_transition_candidate_union as candidate_union
from tools import type_conditioned_sequence_modality_ablation as ablation


def synthetic_rows(boundary: int = 55, length: int = 120):
    rows = []
    for frame in range(length):
        changed = frame >= boundary
        rows.append({
            "visible_H_mean": 25.0 if not changed else 78.0,
            "visible_S_mean": 0.18 if not changed else 0.48,
            "visible_V_mean": 0.45 if not changed else 0.66,
            "thermal_raw_roi_p50": 28.0 if not changed else 30.0,
            "thermal_raw_roi_p95": 29.0 if not changed else 33.0,
        })
    return rows


class TypeConditionedSequenceModalityAblationTests(unittest.TestCase):
    def test_feature_masks_are_disjoint_except_consensus(self):
        names = candidate_union.feature_names()
        color = set(ablation.allowed_feature_indices("color"))
        thermal = set(ablation.allowed_feature_indices("thermal"))
        fusion = set(ablation.allowed_feature_indices("fusion"))
        overlap = {names[index] for index in color & thermal}
        self.assertEqual(overlap, {"candidate_consensus"})
        self.assertEqual(color | thermal, fusion)

    def test_fusion_generation_exactly_matches_frozen_union(self):
        rows = synthetic_rows()
        self.assertEqual(
            ablation.generate_candidates(rows, "fusion"),
            candidate_union.generate_union_candidates(rows),
        )

    def test_color_candidates_ignore_thermal_values(self):
        rows = synthetic_rows()
        changed = copy.deepcopy(rows)
        for index, row in enumerate(changed):
            row["thermal_raw_roi_p50"] = 9000.0 - index
            row["thermal_raw_roi_p95"] = -9000.0 + index
        self.assertEqual(
            ablation.generate_candidates(rows, "color"),
            ablation.generate_candidates(changed, "color"),
        )

    def test_thermal_candidates_ignore_visible_values(self):
        rows = synthetic_rows()
        changed = copy.deepcopy(rows)
        for index, row in enumerate(changed):
            row["visible_H_mean"] = index * 17.0
            row["visible_S_mean"] = 50.0 + index
            row["visible_V_mean"] = -50.0 - index
        self.assertEqual(
            ablation.generate_candidates(rows, "thermal"),
            ablation.generate_candidates(changed, "thermal"),
        )

    def test_unknown_modality_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown modality"):
            ablation.allowed_feature_indices("other")


if __name__ == "__main__":
    unittest.main()
