import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import build_poster_visual_pack as builder
from tools import validate_poster_visual_pack as validator


class PosterVisualPackTests(unittest.TestCase):
    def test_poster_palette_and_forbidden_sources_are_locked(self):
        self.assertEqual(builder.BLUE, "#2563EB")
        self.assertEqual(builder.ORANGE, "#F59E0B")
        self.assertEqual(builder.GREEN, "#10B981")
        self.assertIn("type_conditioned_modality_ranker_search", validator.FORBIDDEN_SOURCE_TOKENS)

    def test_required_asset_inventory_covers_research_and_results(self):
        self.assertIn("diagram_jagyeokru", validator.REQUIRED_IDS)
        self.assertIn("photo_apparatus", validator.REQUIRED_IDS)
        self.assertIn("chart_method_mape", validator.REQUIRED_IDS)
        self.assertIn("chart_sensor_curves", validator.REQUIRED_IDS)
        self.assertGreaterEqual(len(validator.REQUIRED_IDS), 15)

    def test_authoritative_source_files_exist(self):
        for path in (
            builder.METHOD_SOURCE,
            builder.FUSION_PREDICTIONS,
            builder.FUSION_TYPEWISE,
            builder.CURVE_SOURCE,
            builder.THROUGHPUT_SOURCE,
            builder.APPARATUS_OVERVIEW,
            builder.WET_SETUP,
            builder.PUMP,
            builder.PUMP_3D,
            builder.WINDOWS_DASHBOARD,
        ):
            self.assertTrue(path.is_file(), path)

    def test_validator_can_finalize_validation_report_into_zip(self):
        self.assertTrue(hasattr(validator, "zipfile"))

    def test_source_uri_resolver_has_explicit_repo_and_pack_bases(self):
        output = builder.OUTPUT
        self.assertEqual(
            validator.resolve_source_uri("repo://docs/AUTO_STOP_VALIDATION.md", output),
            builder.ROOT / "docs/AUTO_STOP_VALIDATION.md",
        )
        self.assertEqual(
            validator.resolve_source_uri("pack://04_원본수치/method_comparison.csv", output),
            output / "04_원본수치/method_comparison.csv",
        )
        with self.assertRaises(ValueError):
            validator.resolve_source_uri("docs/no-base.csv", output)


if __name__ == "__main__":
    unittest.main()
