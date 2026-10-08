from __future__ import annotations

import argparse
import logging
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from .config import (
    DEFAULT_ROOT_FOLDERS,
    HIERARCHY_LEVELS,
    CrawlerConfig,
)
from .exporter import CsvExporter, MultiExporter, ParquetExporter
from .filesystem import run_scan
from .models import ScanRecord


DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "crawler_result"
DEFAULT_PARQUET_PATH = DEFAULT_OUTPUT_DIR / "STORAGE_ANALYSIS.parquet"
DEFAULT_DUCKDB_PATH = DEFAULT_OUTPUT_DIR / "STORAGE_ANALYSIS.duckdb"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reservoir Engineering hierarchical storage crawler"
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Root folder to scan. May be repeated.",
    )
    parser.add_argument(
        "--use-default-root",
        action="store_true",
        help=f"Explicitly allow the configured default root: {DEFAULT_ROOT_FOLDERS[0]}",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional compatibility CSV output path",
    )
    parser.add_argument(
        "--parquet",
        default=str(DEFAULT_PARQUET_PATH),
        help="Primary Parquet output path",
    )
    parser.add_argument(
        "--no-parquet",
        action="store_true",
        help="Disable Parquet output",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum hierarchy depth to traverse",
    )
    parser.add_argument(
        "--skip-owner-info",
        action="store_true",
        help="Skip Windows ACL owner lookup",
    )
    parser.add_argument(
        "--hierarchy-levels",
        type=int,
        default=HIERARCHY_LEVELS,
        help="Number of hierarchy columns to write",
    )
    parser.add_argument(
        "--analytics-db",
        default=None,
        help="Optional DuckDB database to build after scanning",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def run_from_args(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if args.roots:
        selected_roots = args.roots
    elif args.use_default_root:
        selected_roots = DEFAULT_ROOT_FOLDERS
    else:
        print("ERROR: No root specified.")
        print('Use --root "<folder>" for a test/specific scan.')
        print("Use --use-default-root to deliberately scan the configured default root.")
        return 1

    parquet_path = None if args.no_parquet else Path(args.parquet)
    csv_path = Path(args.output) if args.output else None

    if parquet_path is None and csv_path is None:
        print("ERROR: Both Parquet and CSV outputs are disabled.")
        return 1

    config = CrawlerConfig.from_values(
        root_folders=selected_roots,
        output_path=str(csv_path or (Path.cwd() / "_disabled.csv")),
        max_depth=args.max_depth,
        skip_owner_info=args.skip_owner_info,
        hierarchy_levels=args.hierarchy_levels,
        debug=args.debug,
        parquet_path=str(parquet_path) if parquet_path else None,
    )

    print(f"Python version: {sys.version.split()[0]}")
    print("Reservoir Engineering Storage Crawler")
    print("=" * 45)
    print(f"Roots: {', '.join(str(p) for p in config.root_folders)}")
    print(f"Max depth: {config.max_depth}")
    print(f"Owner lookup: {'disabled' if config.skip_owner_info else 'enabled'}")
    print(f"Parquet: {parquet_path or 'disabled'}")
    print(f"CSV: {csv_path or 'disabled'}")

    start = time.perf_counter()
    output_count = 0
    last_report = 0

    exporters = []
    if csv_path:
        exporters.append(CsvExporter(csv_path, config.hierarchy_levels))
    if parquet_path:
        exporters.append(ParquetExporter(parquet_path, config.hierarchy_levels))

    with ExitStack() as stack:
        multi = stack.enter_context(MultiExporter(exporters))

        def emit(record: ScanRecord) -> None:
            nonlocal output_count, last_report
            multi.write(record)
            output_count += 1

            if output_count - last_report >= 10_000:
                last_report = output_count
                elapsed = time.perf_counter() - start
                logging.info(
                    "Processed %,d records | %.1f records/s",
                    output_count,
                    output_count / elapsed if elapsed else 0.0,
                )

        summary = run_scan(config, emit)

    elapsed = time.perf_counter() - start

    analytics_db = None
    if args.analytics_db and parquet_path:
        from .analytics import create_analytics_database

        analytics_db = Path(args.analytics_db)
        logging.info("Building DuckDB analytical database...")
        create_analytics_database(
            parquet_path=parquet_path,
            database_path=analytics_db,
        )

    print()
    print("SCAN COMPLETE")
    print(f"Total items: {summary.total_items:,}")
    print(f"Folders: {summary.total_folders:,}")
    print(f"Files: {summary.total_files:,}")
    print(f"Max depth: {summary.max_depth_found}")
    print(
        f"Total storage: {summary.total_size_tb:,.3f} TB "
        f"({summary.total_size_gb:,.3f} GB)"
    )
    print(f"Simulation files: {summary.simulation_file_count:,}")
    print(f"Inaccessible paths: {summary.inaccessible_paths:,}")
    print(f"Duration: {elapsed:,.1f} seconds")
    if parquet_path:
        print(f"Parquet saved to: {parquet_path}")
    if csv_path:
        print(f"CSV saved to: {csv_path}")
    if analytics_db:
        print(f"DuckDB saved to: {analytics_db}")

    return 0


def main() -> int:
    parser = build_parser()
    return run_from_args(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
