from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .config import (
    DEFAULT_OUTPUT_PATH,
    DEFAULT_ROOT_FOLDERS,
    HIERARCHY_LEVELS,
    CrawlerConfig,
)
from .exporter import CsvExporter, csv_to_parquet
from .filesystem import run_scan
from .models import ScanRecord


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reservoir Engineering hierarchical storage crawler"
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help=f"Root folder to scan. May be repeated. Default: {DEFAULT_ROOT_FOLDERS[0]}",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="CSV output path",
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
        "--parquet",
        default=None,
        help="Optional Parquet output path",
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

    config = CrawlerConfig.from_values(
        root_folders=args.roots,
        output_path=args.output,
        max_depth=args.max_depth,
        skip_owner_info=args.skip_owner_info,
        hierarchy_levels=args.hierarchy_levels,
        debug=args.debug,
        parquet_path=args.parquet,
    )

    if not config.root_folders:
        logging.error("No folders specified.")
        return 1

    print(f"Python version: {__import__('sys').version.split()[0]}")
    print("Reservoir Engineering Storage Crawler")
    print("=" * 45)

    start = time.perf_counter()
    output_count = 0
    last_report = 0

    with CsvExporter(config.output_path, config.hierarchy_levels) as exporter:

        def emit(record: ScanRecord) -> None:
            nonlocal output_count, last_report
            exporter.write(record)
            output_count += 1
            if output_count - last_report >= 1000:
                last_report = output_count
                logging.info("Processed %s records...", output_count)

        summary = run_scan(config, emit)

    if config.parquet_path:
        csv_to_parquet(config.output_path, config.parquet_path)

    elapsed = time.perf_counter() - start

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
    print(f"Report saved to: {config.output_path}")

    if config.parquet_path:
        print(f"Parquet saved to: {config.parquet_path}")

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_from_args(args)


if __name__ == "__main__":
    raise SystemExit(main())
