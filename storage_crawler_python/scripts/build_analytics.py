from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage_crawler.analytics import (
    convert_csv_to_parquet,
    create_analytics_database,
    export_summary_tables,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert crawler CSV to Parquet and build DuckDB summaries."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument("--parquet", default=None)
    parser.add_argument("--database", default=None)
    parser.add_argument("--summary-dir", default=None)
    parser.add_argument("--stale-days", type=int, default=730)
    parser.add_argument("--largest-file-limit", type=int, default=10_000)
    parser.add_argument("--row-group-size", type=int, default=500_000)
    parser.add_argument("--memory-limit", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    parquet_path = Path(
        args.parquet or csv_path.with_name("STORAGE_ANALYSIS.parquet")
    )
    database_path = Path(
        args.database or csv_path.with_name("STORAGE_ANALYSIS.duckdb")
    )
    summary_dir = Path(
        args.summary_dir or csv_path.parent / "analytics"
    )

    if not parquet_path.exists() or args.force:
        print("[1/3] CSV -> Parquet")
        convert_csv_to_parquet(
            csv_path=csv_path,
            parquet_path=parquet_path,
            row_group_size=args.row_group_size,
            memory_limit=args.memory_limit,
        )
    else:
        print(f"[1/3] Parquet already exists: {parquet_path}")

    print("[2/3] Building DuckDB analytical database")
    create_analytics_database(
        parquet_path=parquet_path,
        database_path=database_path,
        stale_days=args.stale_days,
        largest_file_limit=args.largest_file_limit,
        memory_limit=args.memory_limit,
    )

    print("[3/3] Exporting compact summary tables")
    outputs = export_summary_tables(
        database_path=database_path,
        output_dir=summary_dir,
        formats=("csv",),
    )

    print()
    print("ANALYTICS BUILD COMPLETE")
    print(f"Parquet : {parquet_path}")
    print(f"DuckDB  : {database_path}")
    print(f"Summary : {summary_dir}")
    for output in outputs:
        print(f"  - {output.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
