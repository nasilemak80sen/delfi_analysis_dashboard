from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .config import CSV_HEADERS
from .models import ScanRecord


class CsvExporter:
    def __init__(self, path: Path, hierarchy_levels: int = 10):
        self.path = Path(path)
        self.hierarchy_levels = hierarchy_levels
        self._handle = None
        self._writer = None

    def __enter__(self) -> "CsvExporter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        )
        headers = CSV_HEADERS[:16] + [
            f"L{i}_Name" for i in range(1, self.hierarchy_levels + 1)
        ]
        self._writer = csv.writer(self._handle, quoting=csv.QUOTE_MINIMAL)
        self._writer.writerow(headers)
        return self

    def write(self, record: ScanRecord) -> None:
        if self._writer is None:
            raise RuntimeError("CsvExporter must be used as a context manager")
        self._writer.writerow(record.as_row(self.hierarchy_levels))

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.close()


def csv_to_parquet(csv_path: Path, parquet_path: Path) -> None:
    """
    Convert the compatibility CSV to Parquet.

    This keeps the crawler dependency-light and makes Parquet an explicit
    downstream analytical format.
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for Parquet conversion") from exc

    parquet_path = Path(parquet_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(csv_path, low_memory=False)
    frame.to_parquet(parquet_path, index=False)


def export_records(
    records: Iterable[ScanRecord],
    path: Path,
    hierarchy_levels: int = 10,
) -> None:
    with CsvExporter(path, hierarchy_levels) as exporter:
        for record in records:
            exporter.write(record)
