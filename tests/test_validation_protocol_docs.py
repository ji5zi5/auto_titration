from pathlib import Path
import unittest


DOC = Path("docs/validation_protocol.md")


class ValidationProtocolDocsTests(unittest.TestCase):
    def test_validation_protocol_contains_four_type_matrix_and_safety_checklist(self):
        self.assertTrue(DOC.exists())
        text = DOC.read_text(encoding="utf-8")

        for expected in [
            "strong_acid_strong_base",
            "weak_acid_strong_base",
            "strong_acid_weak_base",
            "weak_acid_weak_base",
            "equivalence point",
            "endpoint",
            "Mini2",
            "palette",
            "`c` stop",
            "maximum volume",
            "PPE",
            "no automatic stop",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
