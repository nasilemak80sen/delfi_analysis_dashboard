from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage_crawler.analytics import reconcile_csv_parquet


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile crawler CSV and Parquet inventories without pandas."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--memory-limit", default=None)
    parser.add_argument("--size-tolerance-gb", type=float, default=1e-6)
    args = parser.parse_args()

    result = reconcile_csv_parquet(
        csv_path=Path(args.csv),
        parquet_path=Path(args.parquet),
        memory_limit=args.memory_limit,
        size_tolerance_gb=args.size_tolerance_gb,
    )

    print("PIPELINE RECONCILIATION")
    print("=" * 50)

    print("CSV metrics:")
    for key, value in result["csv_metrics"].items():
        print(f"  {key}: {value}")

    print()
    print("Parquet metrics:")
    for key, value in result["parquet_metrics"].items():
        print(f"  {key}: {value}")

    print()
    if result["ok"]:
        print("RESULT: PASS")
        print("CSV and Parquet inventory metrics reconcile.")
        return 0

    print("RESULT: FAIL")
    print("Scalar differences:")
    for key, value in result["scalar_differences"].items():
        print(f"  {key}: {value}")

    print("Group differences:")
    for value in result["group_differences"]:
        print(f"  {value}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
