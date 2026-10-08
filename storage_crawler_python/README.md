# Reservoir Engineering Storage Crawler — Python

A PowerShell-compatible Python rewrite of the hierarchical storage crawler.

The project is intentionally split into:
- `storage_crawler/` — production crawler code
- `tests/` — automated validation
- `analysis/` — Jupyter notebooks for data analysis
- `scripts/` — validation/export utilities

## Design goals

1. Preserve the current crawler's business rules and CSV columns.
2. Enforce `MaxDepth` during traversal, rather than after enumerating the entire tree.
3. Avoid materialising the entire filesystem into one `$allItems`-equivalent collection.
4. Keep owner retrieval optional and cached.
5. Make file classification configurable in one place.
6. Make Parquet the primary analytical output and keep CSV as an optional compatibility/export format.
7. Make the crawler testable without requiring access to the production drive.

## Requirements

- Windows
- Python 3.10+ recommended
- PowerShell 5.1 or later on the host if owner lookup is enabled
- `pytest`
- `pandas` + `pyarrow` for notebook/Parquet analysis

Install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run

Compatibility-style run:

```powershell
python -m storage_crawler.main `
  --root "X:\Reservoir Engineering" `
  --output "$env:USERPROFILE\Documents\crawler_result\STORAGE_ANALYSIS.csv" `
  --max-depth 5
```

Multiple roots:

```powershell
python -m storage_crawler.main `
  --root "X:\Reservoir Engineering" `
  --root "Y:\Reservoir Engineering" `
  --output "$env:USERPROFILE\Documents\crawler_result\STORAGE_ANALYSIS.csv"
```

Skip owner lookup for a faster scan:

```powershell
python -m storage_crawler.main `
  --root "X:\Reservoir Engineering" `
  --skip-owner-info
```

Enable optional Parquet conversion:

```powershell
python -m storage_crawler.main `
  --root "X:\Reservoir Engineering" `
  --output "$env:USERPROFILE\Documents\crawler_result\STORAGE_ANALYSIS.csv" `
  --parquet "$env:USERPROFILE\Documents\crawler_result\STORAGE_ANALYSIS.parquet"
```

## Important compatibility notes

- The root folder itself is not emitted as a record, matching the current PowerShell `Get-ChildItem -Recurse` approach.
- `Drive` is derived from the root path, e.g. `X:`.
- `ItemID` is assigned sequentially during Python traversal. Item IDs/order do not need to match PowerShell byte-for-byte because filesystem enumeration order can differ.
- Parent/child relationships are matched by normalised paths.
- Folder size is the sum of scanned descendant file sizes.
- `FileCountInFolder` is the direct-file count for that folder.
- Folder `IsSimulationFile` and `FileCategory` are `N/A`.
- Files are classified from their extensions using `storage_crawler/classifier.py`.
- The owner lookup intentionally mirrors the current optimisation: direct ACL lookup for depth <= 3, then parent-owner inheritance where available.

## CSV -> Parquet pipeline validation

After converting an existing inventory CSV, reconcile the source CSV and generated
Parquet without loading the full dataset into pandas:

```powershell
py -3.13 scripts\\validate_pipeline.py `
  --csv "path\\to\\STORAGE_ANALYSIS.csv" `
  --parquet "path\\to\\STORAGE_ANALYSIS.parquet" `
  --memory-limit 4GB
```

The reconciliation checks:
- total rows
- file/folder counts
- total file storage
- simulation file count
- distinct and duplicate paths
- missing paths
- maximum depth
- file-category counts and storage by drive/item type

The command exits with code `0` only when the source and Parquet metrics reconcile.

## Validation against the existing PowerShell crawler

After running both crawlers against the same test/production root, use:

```powershell
python scripts\compare_outputs.py `
  --powershell "path\to\STORAGE_ANALYSIS_PS.csv" `
  --python "path\to\STORAGE_ANALYSIS.csv"
```

The comparison focuses on:
- missing/extra paths
- file/folder counts
- total file storage
- simulation file count
- file classification differences
- folder-size differences

It deliberately does not require identical `ItemID` values or row order.

## Suggested workflow

1. Run the Python crawler on a small test folder.
2. Run the PowerShell crawler on the same test folder.
3. Compare results.
4. Run `pytest -q`.
5. Convert the production CSV to Parquet with the schema-driven pipeline.
6. Run `scripts\validate_pipeline.py` and investigate any differences.
7. Build the DuckDB analytical layer and validate its summary tables.
8. Build the Jupyter analysis layer.
9. Feed the validated dataset to Power BI.



## Large-data architecture

For large inventories, Parquet is the primary storage format and CSV is only a
compatibility/export format. DuckDB sits above Parquet and builds small analytical
tables for Jupyter and Power BI.

The crawler writes Parquet in bounded batches through PyArrow. It does not build
the full inventory in pandas.

For an existing large CSV:

py -3.13 -m pip install --user duckdb pyarrow pandas jupyterlab

py -3.13 scripts\build_analytics.py --csv "C:\path\to\STORAGE_ANALYSIS.csv" --memory-limit 4GB

This produces a Parquet file, a small DuckDB database, and compact summary tables.

Do not use a full-data pandas read such as df = pd.read_csv(...) for the 3.5 GB
inventory.

