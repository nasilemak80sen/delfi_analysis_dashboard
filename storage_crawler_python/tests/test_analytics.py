from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pyarrow = pytest.importorskip("pyarrow")
import pyarrow.parquet as pq

from storage_crawler.analytics import create_analytics_database


def _write_fixture(path: Path) -> None:
    import pyarrow as pa

    schema = pa.schema([
        ("Drive", pa.string()),
        ("ItemID", pa.int64()),
        ("ParentID", pa.int64()),
        ("ItemType", pa.string()),
        ("ItemName", pa.string()),
        ("FileExtension", pa.string()),
        ("FullPath", pa.string()),
        ("Depth", pa.int64()),
        ("Owner", pa.string()),
        ("SizeMB", pa.float64()),
        ("SizeGB", pa.float64()),
        ("FileCountInFolder", pa.int64()),
        ("LastModified", pa.string()),
        ("IsSimulationFile", pa.string()),
        ("FileCategory", pa.string()),
        ("ScanDateTime", pa.string()),
        ("L1_Name", pa.string()),
        ("L2_Name", pa.string()),
        ("L3_Name", pa.string()),
        ("L4_Name", pa.string()),
    ])

    rows = [
        ["X:", 1, 0, "File", "a.sim", ".sim", r"X:\\A\\a.sim", 2, "OWNER",
         10.0, 0.01, 0, "2026-01-01 10:00:00", "Yes",
         "Simulation Model", "2026-10-08 10:00:00", "A", "a.sim", "", ""],
        ["X:", 2, 0, "File", "b.txt", ".txt", r"X:\\A\\b.txt", 2, "OWNER",
         20.0, 0.02, 0, "2026-10-08 10:00:00", "No",
         "Text/Log", "2026-10-08 10:00:00", "A", "b.txt", "", ""],
    ]

    table = pa.Table.from_pylist(
        [dict(zip(schema.names, row)) for row in rows],
        schema=schema,
    )
    pq.write_table(table, path, compression="zstd")


def test_create_analytics_database(tmp_path: Path):
    parquet = tmp_path / "storage.parquet"
    database = tmp_path / "storage.duckdb"

    _write_fixture(parquet)
    create_analytics_database(
        parquet,
        database,
        stale_days=1,
        largest_file_limit=10,
    )

    con = duckdb.connect(str(database), read_only=True)
    quality = con.sql("SELECT * FROM data_quality").fetchone()

    assert quality[0] == 2
    assert quality[1] == 2

    categories = con.sql(
        "SELECT FileCategory, storage_gb "
        "FROM category_summary ORDER BY storage_gb DESC"
    ).fetchall()

    assert {row[0] for row in categories} == {
        "Simulation Model",
        "Text/Log",
    }