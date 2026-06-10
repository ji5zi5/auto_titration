"""CSV logging for synchronized titration camera features."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping

from .data_schema import DEFAULT_COLUMNS


class CsvDataLogger:
    """Write rows with stable schema columns, leaving missing values blank."""

    def __init__(self, path: str | Path, columns: Iterable[str] = DEFAULT_COLUMNS) -> None:
        self.path = Path(path)
        self.columns = list(columns)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.columns, extrasaction="ignore")
        self._writer.writeheader()

    def write_row(self, row: Mapping[str, Any]) -> None:
        normalized = {column: row.get(column, "") for column in self.columns}
        self._writer.writerow(normalized)
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "CsvDataLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()
