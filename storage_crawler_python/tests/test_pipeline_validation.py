from datetime import datetime
from pathlib import Path
import csv

import pytest

duckdb = pytest.importorskip("duckdb")
pyarrow = pytest.importorskip("pyarrow")

from storage_crawler.analytics import (
    CSV_DUCKDB_TYPES,
    convert_csv_to_parquet,
    reconcile_csv_parquet,
)
from storage_crawler.config import CSV_HEADERS
from storage_crawler.exporter import CsvExporter
from storage_crawler.models import ScanRecord


def _record(item_id: int, name: str, path: str, *, item_type: str = "File") -> ScanRecord:
    return ScanRecord(
        drive="X:",
        item_id=item_id,
        parent_id=0,
        item_type=item_type,
        item_name=name,
        file_extension=Path(name).suffix if item_type == "File" else "",
        full_path=path,
        depth=2,
        owner="DOMAIN\\User",
        size_mb=20.0 if item_type == "File" else 0.0,
        size_gb=20.0 / 1024 if item_type == "File" else 0.0,
        file_count_in_folder=0,
        last_modified=datetime(2026, 9, 24, 10, 30, 0),
        is_simulation_file="Yes" if name.endswith(".sim") else "No",
        file_category="Simulation Model" if name.endswith(".sim") else "Text/Log",
        scan_datetime=datetime(2026, 9, 24, 10, 30, 1),
        hierarchy=(name,),
    )


def _write_csv(path: Path) -> None:
    records = [
        _record(
            1,
            "model,rev 2 (final).sim",
            r"X:\Reservoir Engineering\Models\model,rev 2 (final).sim",
        ),
        _record(
            2,
            "notes (final), v3.txt",
            r"X:\Reservoir Engineering\Docs\notes (final), v3.txt",
        ),
        _record(
            3,
            "Models",
            r"X:\Reservoir Engineering\Models",
            item_type="Folder",
        ),
    ]

    with CsvExporter(path) as exporter:
        for record in records:
            exporter.write(record)


def test_csv_schema_matches_crawler_headers():
    assert list(CSV_DUCKDB_TYPES) == CSV_HEADERS
    assert len(CSV_DUCKDB_TYPES) == 26


def test_convert_csv_with_quoted_commas_and_windows_paths(tmp_path: Path):
    csv_path = tmp_path / "inventory.csv"
    parquet_path = tmp_path / "inventory.parquet"
    _write_csv(csv_path)

    convert_csv_to_parquet(csv_path, parquet_path, row_group_size=2)

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT ItemName, FullPath, Depth
        FROM read_parquet('{parquet_path.as_posix()}')
        ORDER BY ItemID
        """
    ).fetchall()
    con.close()

    assert rows == [
        (
            "model,rev 2 (final).sim",
            r"X:\Reservoir Engineering\Models\model,rev 2 (final).sim",
            2,
        ),
        (
            "notes (final), v3.txt",
            r"X:\Reservoir Engineering\Docs\notes (final), v3.txt",
            2,
        ),
        ("Models", r"X:\Reservoir Engineering\Models", 2),
    ]


def test_reconcile_csv_and_parquet(tmp_path: Path):
    csv_path = tmp_path / "inventory.csv"
    parquet_path = tmp_path / "inventory.parquet"
    _write_csv(csv_path)

    convert_csv_to_parquet(csv_path, parquet_path)

    result = reconcile_csv_parquet(csv_path, parquet_path)

    assert result["ok"] is True
    assert result["scalar_differences"] == {}
    assert result["group_differences"] == []


def test_failed_conversion_does_not_leave_partial_parquet(tmp_path: Path):
    csv_path = tmp_path / "broken.csv"
    parquet_path = tmp_path / "inventory.parquet"

    csv_path.write_text(
        "\ufeffDrive,ItemID,ParentID,ItemType,ItemName,FileExtension,FullPath,Depth,"
        "Owner,SizeMB,SizeGB,FileCountInFolder,LastModified,IsSimulationFile,"
        "FileCategory,ScanDateTime,L1_Name,L2_Name,L3_Name,L4_Name,L5_Name,L6_Name,"
        "L7_Name,L8_Name,L9_Name,L10_Name\n"
        "X:,not-an-int,0,File,bad.txt,.txt,X:\\\\bad.txt,1,OWNER,1,0.001,0,"
        "2026-09-24 10:30:00,No,Text/Log,2026-09-24 10:30:01,,,,,,,,,,\n",
        encoding="utf-8",
        newline="",
    )

    with pytest.raises(Exception):
        convert_csv_to_parquet(csv_path, parquet_path)

    assert not parquet_path.exists()
    assert not parquet_path.with_name("inventory.parquet.part").exists()
