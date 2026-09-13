import unittest

from tools import search_type_conditioned_modality_rankers as search


class SearchTypeConditionedModalityRankersTests(unittest.TestCase):
    def test_coarse_search_space_matches_fused_search_shape(self):
        self.assertEqual(len(search.coarse_aggregations()), 81)
        self.assertEqual(search.TYPE_NAMES, (
            "strong_acid_strong_base",
            "weak_acid_strong_base",
            "strong_acid_weak_base",
            "weak_acid_weak_base",
        ))

    def test_dense_grids_cover_global_and_same_type_models(self):
        for titration_type in search.TYPE_NAMES:
            weights, temperatures, blends, top_ks = search._dense_grid(titration_type)
            self.assertEqual(float(weights[0]), 0.0)
            self.assertEqual(float(weights[-1]), 1.0)
            self.assertIn(1, top_ks)
            self.assertIn(0, top_ks)
            self.assertGreater(len(temperatures), 20)
            self.assertGreater(len(blends), 10)

    def test_invalid_modality_is_rejected_before_data_load(self):
        with self.assertRaisesRegex(ValueError, "unknown modality"):
            search.run_search("other")


if __name__ == "__main__":
    unittest.main()
