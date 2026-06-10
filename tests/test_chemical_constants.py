import csv
import tempfile
import unittest
from pathlib import Path

from auto_titrator.chemical_constants import (
    DEFAULT_IUPAC_CSV_PATH,
    IupacPkaDatabase,
    lookup_iupac_pka,
    parse_pka_value,
)


FIELDNAMES = [
    "unique_ID",
    "SMILES",
    "InChI",
    "pka_type",
    "pka_value",
    "T",
    "remarks",
    "method",
    "assessment",
    "ref",
    "ref_remarks",
    "entry_remarks",
    "original_IUPAC_names",
    "name_contributors",
    "num_name_contributors",
    "original_IUPAC_nicknames",
    "source",
    "pressure",
    "acidity_label",
    "original_T",
    "cosolvent",
]


class IupacChemicalConstantsTests(unittest.TestCase):
    def make_database(self) -> IupacPkaDatabase:
        rows = [
            {
                "unique_ID": "acid-1",
                "SMILES": "CC(=O)O",
                "InChI": "InChI=1S/C2H4O2/c1-2(3)4/h1H3,(H,3,4)",
                "pka_type": "pKa1",
                "pka_value": "4.76",
                "T": "25",
                "remarks": "aqueous",
                "method": "pot",
                "assessment": "Reliable",
                "ref": "serjeant",
                "ref_remarks": "",
                "entry_remarks": "",
                "original_IUPAC_names": "Acetic acid",
                "name_contributors": "",
                "num_name_contributors": "",
                "original_IUPAC_nicknames": "Ethanoic acid",
                "source": "serjeant",
                "pressure": "",
                "acidity_label": "A",
                "original_T": "25 C",
                "cosolvent": "",
            },
            {
                "unique_ID": "acid-2",
                "SMILES": "CC(=O)O",
                "InChI": "InChI=1S/C2H4O2/c1-2(3)4/h1H3,(H,3,4)",
                "pka_type": "pKaH1",
                "pka_value": "-6.1",
                "T": "<25",
                "remarks": "monoprotonated species",
                "method": "",
                "assessment": "Uncertain",
                "ref": "perrin",
                "ref_remarks": "",
                "entry_remarks": "",
                "original_IUPAC_names": "Acetic acid",
                "name_contributors": "",
                "num_name_contributors": "",
                "original_IUPAC_nicknames": "",
                "source": "perrin",
                "pressure": "",
                "acidity_label": "AH",
                "original_T": "<25",
                "cosolvent": "",
            },
            {
                "unique_ID": "weak-base-1",
                "SMILES": "NCCO",
                "InChI": "",
                "pka_type": "pKaH1",
                "pka_value": "<9.5",
                "T": "20",
                "remarks": "example bound",
                "method": "",
                "assessment": "Approximate",
                "ref": "perrin",
                "ref_remarks": "",
                "entry_remarks": "",
                "original_IUPAC_names": "2-Aminoethanol",
                "name_contributors": "",
                "num_name_contributors": "",
                "original_IUPAC_nicknames": "Ethanolamine",
                "source": "perrin",
                "pressure": "",
                "acidity_label": "AH",
                "original_T": "20 C",
                "cosolvent": "",
            },
            {
                "unique_ID": "cosolvent-1",
                "SMILES": "CC(=O)O",
                "InChI": "",
                "pka_type": "pKa1",
                "pka_value": "5.2",
                "T": "25",
                "remarks": "cosolvent example",
                "method": "",
                "assessment": "Reliable",
                "ref": "example",
                "ref_remarks": "",
                "entry_remarks": "",
                "original_IUPAC_names": "Acetic acid",
                "name_contributors": "",
                "num_name_contributors": "",
                "original_IUPAC_nicknames": "",
                "source": "example",
                "pressure": "",
                "acidity_label": "A",
                "original_T": "25 C",
                "cosolvent": "DMSO",
            },
        ]
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "iupac_fixture.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        return IupacPkaDatabase.load(path)

    def test_default_iupac_csv_exists(self):
        self.assertTrue(DEFAULT_IUPAC_CSV_PATH.exists())

    def test_parse_pka_value_handles_bounds(self):
        parsed = parse_pka_value("<9.5")
        self.assertEqual(parsed.value, 9.5)
        self.assertEqual(parsed.qualifier, "<")

        parsed = parse_pka_value("4.76")
        self.assertEqual(parsed.value, 4.76)
        self.assertEqual(parsed.qualifier, "")

    def test_exact_name_lookup_preserves_source_metadata(self):
        db = self.make_database()
        result = db.lookup("Acetic acid")

        self.assertFalse(result.requires_manual_confirmation)
        self.assertGreaterEqual(len(result.candidates), 2)
        best = result.candidates[0]
        self.assertEqual(best.unique_id, "acid-1")
        self.assertEqual(best.name, "Acetic acid")
        self.assertEqual(best.pka_type, "pKa1")
        self.assertAlmostEqual(best.pka_value, 4.76)
        self.assertEqual(best.temperature_c, 25.0)
        self.assertEqual(best.assessment, "Reliable")
        self.assertEqual(best.source, "serjeant")
        self.assertEqual(best.acidity_label, "A")
        self.assertEqual(best.match_type, "exact_name")

    def test_nickname_and_smiles_lookup_work(self):
        db = self.make_database()

        by_nickname = db.lookup("ethanoic acid")
        self.assertEqual(by_nickname.candidates[0].unique_id, "acid-1")
        self.assertEqual(by_nickname.candidates[0].match_type, "exact_nickname")

        by_smiles = db.lookup("CC(=O)O")
        self.assertEqual(by_smiles.candidates[0].unique_id, "acid-1")
        self.assertEqual(by_smiles.candidates[0].match_type, "exact_smiles")

    def test_ambiguous_query_returns_candidates_without_silent_collapse(self):
        db = self.make_database()
        result = db.lookup("acid", limit=10)

        self.assertGreaterEqual(len(result.candidates), 3)
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.requires_manual_confirmation)

    def test_missing_query_requires_manual_confirmation(self):
        db = self.make_database()
        result = db.lookup("unobtainium hydroxide")

        self.assertEqual(result.candidates, [])
        self.assertTrue(result.requires_manual_confirmation)
        self.assertIn("No IUPAC", result.warning)

    def test_ranking_prefers_reliable_aqueous_25c_records(self):
        db = self.make_database()
        result = db.lookup("Acetic acid")
        ids = [candidate.unique_id for candidate in result.candidates]

        self.assertLess(ids.index("acid-1"), ids.index("cosolvent-1"))
        self.assertLess(ids.index("acid-1"), ids.index("acid-2"))

    def test_real_acetic_acid_lookup_prefers_ordinary_aqueous_pka1(self):
        result = lookup_iupac_pka("acetic acid", limit=5)

        self.assertGreaterEqual(len(result.candidates), 1)
        best = result.candidates[0]
        self.assertEqual(best.pka_type, "pKa1")
        self.assertGreater(best.pka_value, 4.7)
        self.assertLess(best.pka_value, 4.8)
        self.assertNotIn("d2o", best.cosolvent.casefold())
        self.assertNotIn("(0-d", best.pka_type.casefold())


if __name__ == "__main__":
    unittest.main()
