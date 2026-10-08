from __future__ import annotations

import argparse
import csv
import math
import os
from collections import Counter


def path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def load(path: str) -> dict[str, dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {path_key(row["FullPath"]): row for row in rows}


def float_value(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    return float(value) if value else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--powershell", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--tolerance-gb", type=float, default=0.000001)
    args = parser.parse_args()

    ps = load(args.powershell)
    py = load(args.python)

    ps_keys = set(ps)
    py_keys = set(py)

    missing = sorted(ps_keys - py_keys)
    extra = sorted(py_keys - ps_keys)

    print("=== DATASET COMPARISON ===")
    print(f"PowerShell rows : {len(ps):,}")
    print(f"Python rows     : {len(py):,}")
    print(f"Missing in Python: {len(missing):,}")
    print(f"Extra in Python  : {len(extra):,}")

    def counts(dataset: dict[str, dict[str, str]]):
        folders = sum(r["ItemType"] == "Folder" for r in dataset.values())
        files = sum(r["ItemType"] == "File" for r in dataset.values())
        sim = sum(r["IsSimulationFile"] == "Yes" for r in dataset.values())
        total_gb = sum(
            float_value(r, "SizeGB")
            for r in dataset.values()
            if r["ItemType"] == "File"
        )
        return folders, files, sim, total_gb

    ps_counts = counts(ps)
    py_counts = counts(py)

    labels = ["Folders", "Files", "Simulation files", "File storage GB"]
    for label, a, b in zip(labels, ps_counts, py_counts):
        if label == "File storage GB":
            print(f"{label:20}: PS={a:,.6f} | PY={b:,.6f} | Δ={b-a:,.6f}")
        else:
            print(f"{label:20}: PS={a:,} | PY={b:,} | Δ={b-a:,}")

    classification_diffs = []
    folder_size_diffs = []

    shared = ps_keys & py_keys
    for key in shared:
        ps_row = ps[key]
        py_row = py[key]

        if ps_row["ItemType"] == "File":
            fields = ("FileExtension", "IsSimulationFile", "FileCategory")
            if any(ps_row[f] != py_row[f] for f in fields):
                classification_diffs.append(
                    (key, {f: (ps_row[f], py_row[f]) for f in fields})
                )

        if ps_row["ItemType"] == "Folder":
            delta = abs(
                float_value(ps_row, "SizeGB") - float_value(py_row, "SizeGB")
            )
            if delta > args.tolerance_gb:
                folder_size_diffs.append((key, delta))

    print(f"Classification differences: {len(classification_diffs):,}")
    print(f"Folder-size differences   : {len(folder_size_diffs):,}")

    if missing:
        print("\nFirst 20 missing paths:")
        for item in missing[:20]:
            print("  ", ps[item]["FullPath"])

    if extra:
        print("\nFirst 20 extra paths:")
        for item in extra[:20]:
            print("  ", py[item]["FullPath"])

    if classification_diffs:
        print("\nFirst 10 classification differences:")
        for key, diff in classification_diffs[:10]:
            print("  ", key, diff)

    if folder_size_diffs:
        print("\nFirst 10 folder-size differences:")
        for key, delta in folder_size_diffs[:10]:
            print(f"  {key}: Δ={delta:.6f} GB")

    return 0 if not missing and not extra and not classification_diffs else 2


if __name__ == "__main__":
    raise SystemExit(main())
