import csv
import tempfile
import unittest
from pathlib import Path

from auto_titrator.data_logger import CsvDataLogger, DEFAULT_COLUMNS
from auto_titrator.data_schema import DEFAULT_COLUMNS as SCHEMA_COLUMNS


class CsvDataLoggerTests(unittest.TestCase):
    def test_writes_default_columns_and_row_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.csv"
            logger = CsvDataLogger(path)
            logger.write_row({
                "time_s": 1.25,
                "frame_id": 7,
                "visible_R_mean": 120.0,
                "thermal_H_mean": 42.0,
            })
            logger.close()

            with path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(rows[0]["time_s"], "1.25")
        self.assertEqual(rows[0]["frame_id"], "7")
        self.assertEqual(rows[0]["visible_R_mean"], "120.0")
        self.assertEqual(rows[0]["thermal_H_mean"], "42.0")
        self.assertEqual(DEFAULT_COLUMNS, SCHEMA_COLUMNS)
        self.assertEqual(list(rows[0].keys()), SCHEMA_COLUMNS)


if __name__ == "__main__":
    unittest.main()
