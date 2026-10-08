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

    @property
    def headers(self) -> list[str]:
        return CSV_HEADERS[:16] + [
            f"L{i}_Name" for i in range(1, self.hierarchy_levels + 1)
        ]

    def __enter__(self) -> "CsvExporter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        )
        self._writer = csv.writer(self._handle, quoting=csv.QUOTE_MINIMAL)
        self._writer.writerow(self.headers)
        return self

    def write(self, record: ScanRecord) -> None:
        if self._writer is None:
            raise RuntimeError("CsvExporter must be used as a context manager")
        self._writer.writerow(record.as_row(self.hierarchy_levels))

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.close()


class ParquetExporter:
    """
    Streaming Parquet writer.

    Records are buffered in bounded batches and written through PyArrow's
    ParquetWriter. The complete inventory is never materialised in memory.
    """

    def __init__(
        self,
        path: Path,
        hierarchy_levels: int = 10,
        batch_size: int = 50_000,
        compression: str = "zstd",
    ):
        self.path = Path(path)
        self.hierarchy_levels = hierarchy_levels
        self.batch_size = batch_size
        self.compression = compression
        self._rows: list[list[object]] = []
        self._writer = None
        self._schema = None
        self._pa = None
        self._pq = None

    @property
    def headers(self) -> list[str]:
        return CSV_HEADERS[:16] + [
            f"L{i}_Name" for i in range(1, self.hierarchy_levels + 1)
        ]

    def _load_arrow(self) -> None:
        if self._pa is not None:
            return

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError(
                "PyArrow is required for Parquet output. "
                "Install with: py -3.13 -m pip install --user pyarrow"
            ) from exc

        self._pa = pa
        self._pq = pq

        types = [
            pa.string(),
            pa.int64(),
            pa.int64(),
            pa.string(),
            pa.string(),
            pa.string(),
            pa.string(),
            pa.int64(),
            pa.string(),
            pa.float64(),
            pa.float64(),
            pa.int64(),
            pa.string(),
            pa.string(),
            pa.string(),
            pa.string(),
        ]
        types.extend([pa.string()] * self.hierarchy_levels)

        self._schema = pa.schema(
            list(zip(self.headers, types)),
            metadata={
                b"source": b"reservoir-engineering-storage-crawler",
                b"format_version": b"1",
            },
        )

    def __enter__(self) -> "ParquetExporter":
        self._load_arrow()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = self._pq.ParquetWriter(
            str(self.path),
            self._schema,
            compression=self.compression,
            use_dictionary=True,
        )
        return self

    def _flush(self) -> None:
        if not self._rows:
            return

        columns = list(zip(*self._rows))
        arrays = [
            self._pa.array(values, type=field.type)
            for values, field in zip(columns, self._schema)
        ]
        table = self._pa.Table.from_arrays(arrays, schema=self._schema)
        self._writer.write_table(
            table,
            row_group_size=len(self._rows),
        )
        self._rows.clear()

    def write(self, record: ScanRecord) -> None:
        if self._writer is None:
            raise RuntimeError("ParquetExporter must be used as a context manager")

        self._rows.append(record.as_row(self.hierarchy_levels))
        if len(self._rows) >= self.batch_size:
            self._flush()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._flush()
        finally:
            if self._writer is not None:
                self._writer.close()


class MultiExporter:
    """Write every ScanRecord to one or more bounded exporters."""

    def __init__(self, exporters: list[object]):
        self.exporters = exporters
        self._entered: list[object] = []

    def __enter__(self) -> "MultiExporter":
        for exporter in self.exporters:
            self._entered.append(exporter.__enter__())
        return self

    def write(self, record: ScanRecord) -> None:
        for exporter in self._entered:
            exporter.write(record)

    def __exit__(self, exc_type, exc, tb) -> None:
        for exporter in reversed(self._entered):
            exporter.__exit__(exc_type, exc, tb)


def csv_to_parquet(
    csv_path: Path,
    parquet_path: Path,
    row_group_size: int = 500_000,
    memory_limit: str | None = None,
) -> None:
    """Compatibility wrapper that converts CSV through DuckDB, never pandas."""
    from .analytics import convert_csv_to_parquet

    convert_csv_to_parquet(
        csv_path=csv_path,
        parquet_path=parquet_path,
        row_group_size=row_group_size,
        memory_limit=memory_limit,
    )


def export_records(
    records: Iterable[ScanRecord],
    path: Path,
    hierarchy_levels: int = 10,
) -> None:
    with CsvExporter(path, hierarchy_levels) as exporter:
        for record in records:
            exporter.write(record)
