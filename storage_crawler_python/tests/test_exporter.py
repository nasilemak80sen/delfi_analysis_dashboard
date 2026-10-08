from datetime import datetime
import csv
from pathlib import Path

from storage_crawler.exporter import CsvExporter
from storage_crawler.models import ScanRecord


def test_csv_export(tmp_path: Path):
    output = tmp_path / "output.csv"
    record = ScanRecord(
        drive="X:",
        item_id=1,
        parent_id=0,
        item_type="File",
        item_name="example,with,comma.sim",
        file_extension=".sim",
        full_path=r"X:\Reservoir Engineering\example,with,comma.sim",
        depth=1,
        owner="DOMAIN\\User",
        size_mb=1.0,
        size_gb=1.0 / 1024,
        file_count_in_folder=0,
        last_modified=datetime(2026, 9, 24, 10, 30, 0),
        is_simulation_file="Yes",
        file_category="Simulation Model",
        scan_datetime=datetime(2026, 9, 24, 10, 30, 1),
        hierarchy=("example,with,comma.sim",),
    )

    with CsvExporter(output) as exporter:
        exporter.write(record)

    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["ItemName"] == "example,with,comma.sim"
    assert rows[0]["FileCategory"] == "Simulation Model"
