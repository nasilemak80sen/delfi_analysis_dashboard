from __future__ import annotations

import os
from pathlib import Path


def _sql_path(path: Path) -> str:
    return os.fspath(Path(path)).replace("'", "''")


def _require_duckdb():
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "DuckDB is required. Install with: "
            "py -3.13 -m pip install --user duckdb"
        ) from exc
    return duckdb


def connect(
    database: Path | str = ":memory:",
    memory_limit: str | None = None,
):
    duckdb = _require_duckdb()
    con = duckdb.connect(str(database))
    con.execute("SET preserve_insertion_order = false")
    if memory_limit:
        con.execute(f"SET memory_limit = '{memory_limit}'")
    return con


CSV_DUCKDB_TYPES = {
    "Drive": "VARCHAR",
    "ItemID": "BIGINT",
    "ParentID": "BIGINT",
    "ItemType": "VARCHAR",
    "ItemName": "VARCHAR",
    "FileExtension": "VARCHAR",
    "FullPath": "VARCHAR",
    "Depth": "BIGINT",
    "Owner": "VARCHAR",
    "SizeMB": "DOUBLE",
    "SizeGB": "DOUBLE",
    "FileCountInFolder": "BIGINT",
    "LastModified": "VARCHAR",
    "IsSimulationFile": "VARCHAR",
    "FileCategory": "VARCHAR",
    "ScanDateTime": "VARCHAR",
    **{f"L{i}_Name": "VARCHAR" for i in range(1, 11)},
}

_CSV_COLUMNS_SQL = "{ " + ", ".join(
    f"'{name}': '{dtype}'" for name, dtype in CSV_DUCKDB_TYPES.items()
) + " }"


def _csv_relation_sql(csv_path: Path) -> str:
    return (
        f"read_csv('{_sql_path(csv_path)}', "
        "header = true, "
        "delim = ',', "
        "quote = '\"', "
        "escape = '\"', "
        f"columns = {_CSV_COLUMNS_SQL}, "
        "strict_mode = true, "
        "null_padding = false)"
    )


def convert_csv_to_parquet(
    csv_path: Path,
    parquet_path: Path,
    row_group_size: int = 500_000,
    memory_limit: str | None = None,
) -> Path:
    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    if row_group_size <= 0:
        raise ValueError("row_group_size must be > 0")

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = parquet_path.with_name(parquet_path.name + ".part")

    if temp_path.exists():
        temp_path.unlink()

    con = connect(memory_limit=memory_limit)
    try:
        con.execute(
            f"""
            COPY (
                SELECT *
                FROM {_csv_relation_sql(csv_path)}
            )
            TO '{_sql_path(temp_path)}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                ROW_GROUP_SIZE {int(row_group_size)}
            )
            """
        )
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        con.close()

    temp_path.replace(parquet_path)
    return parquet_path


def _inventory_metrics(con, relation_sql: str) -> dict[str, object]:
    row = con.execute(
        f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNT(*) FILTER (WHERE ItemType = 'File') AS file_count,
            COUNT(*) FILTER (WHERE ItemType = 'Folder') AS folder_count,
            COALESCE(
                SUM(SizeGB) FILTER (WHERE ItemType = 'File'),
                0
            ) AS total_file_storage_gb,
            COUNT(*) FILTER (
                WHERE ItemType = 'File'
                  AND IsSimulationFile = 'Yes'
            ) AS simulation_file_count,
            COUNT(DISTINCT FullPath) AS distinct_paths,
            COUNT(*) - COUNT(DISTINCT FullPath) AS duplicate_path_rows,
            COUNT(*) FILTER (
                WHERE FullPath IS NULL OR FullPath = ''
            ) AS missing_paths,
            MAX(Depth) AS max_depth
        FROM {relation_sql}
        """
    ).fetchone()

    return {
        "total_rows": int(row[0] or 0),
        "file_count": int(row[1] or 0),
        "folder_count": int(row[2] or 0),
        "total_file_storage_gb": float(row[3] or 0.0),
        "simulation_file_count": int(row[4] or 0),
        "distinct_paths": int(row[5] or 0),
        "duplicate_path_rows": int(row[6] or 0),
        "missing_paths": int(row[7] or 0),
        "max_depth": int(row[8] or 0),
    }


def _inventory_groups(con, relation_sql: str) -> dict[tuple[str, str, str], tuple[int, float]]:
    rows = con.execute(
        f"""
        SELECT
            COALESCE(Drive, '') AS Drive,
            COALESCE(ItemType, '') AS ItemType,
            COALESCE(FileCategory, '') AS FileCategory,
            COUNT(*) AS row_count,
            COALESCE(
                SUM(SizeGB) FILTER (WHERE ItemType = 'File'),
                0
            ) AS storage_gb
        FROM {relation_sql}
        GROUP BY Drive, ItemType, FileCategory
        """
    ).fetchall()

    return {
        (str(row[0]), str(row[1]), str(row[2])): (
            int(row[3]),
            float(row[4] or 0.0),
        )
        for row in rows
    }


def reconcile_csv_parquet(
    csv_path: Path,
    parquet_path: Path,
    memory_limit: str | None = None,
    size_tolerance_gb: float = 1e-6,
) -> dict[str, object]:
    csv_path = Path(csv_path)
    parquet_path = Path(parquet_path)

    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    if not parquet_path.exists():
        raise FileNotFoundError(parquet_path)
    if size_tolerance_gb < 0:
        raise ValueError("size_tolerance_gb must be >= 0")

    con = connect(memory_limit=memory_limit)
    try:
        csv_relation = _csv_relation_sql(csv_path)
        parquet_relation = f"read_parquet('{_sql_path(parquet_path)}')"

        csv_metrics = _inventory_metrics(con, csv_relation)
        parquet_metrics = _inventory_metrics(con, parquet_relation)

        scalar_differences: dict[str, object] = {}
        for key in (
            "total_rows",
            "file_count",
            "folder_count",
            "simulation_file_count",
            "distinct_paths",
            "duplicate_path_rows",
            "missing_paths",
            "max_depth",
        ):
            if csv_metrics[key] != parquet_metrics[key]:
                scalar_differences[key] = {
                    "csv": csv_metrics[key],
                    "parquet": parquet_metrics[key],
                }

        csv_storage = float(csv_metrics["total_file_storage_gb"])
        parquet_storage = float(parquet_metrics["total_file_storage_gb"])
        storage_delta = parquet_storage - csv_storage
        if abs(storage_delta) > size_tolerance_gb:
            scalar_differences["total_file_storage_gb"] = {
                "csv": csv_storage,
                "parquet": parquet_storage,
                "delta": storage_delta,
            }

        csv_groups = _inventory_groups(con, csv_relation)
        parquet_groups = _inventory_groups(con, parquet_relation)

        group_differences: list[dict[str, object]] = []
        for key in sorted(set(csv_groups) | set(parquet_groups)):
            csv_value = csv_groups.get(key, (0, 0.0))
            parquet_value = parquet_groups.get(key, (0, 0.0))
            if (
                csv_value[0] != parquet_value[0]
                or abs(csv_value[1] - parquet_value[1]) > size_tolerance_gb
            ):
                group_differences.append(
                    {
                        "drive": key[0],
                        "item_type": key[1],
                        "file_category": key[2],
                        "csv_count": csv_value[0],
                        "parquet_count": parquet_value[0],
                        "csv_storage_gb": csv_value[1],
                        "parquet_storage_gb": parquet_value[1],
                    }
                )

        return {
            "ok": not scalar_differences and not group_differences,
            "csv_metrics": csv_metrics,
            "parquet_metrics": parquet_metrics,
            "scalar_differences": scalar_differences,
            "group_differences": group_differences,
        }
    finally:
        con.close()


def create_analytics_database(
    parquet_path: Path,
    database_path: Path,
    stale_days: int = 730,
    largest_file_limit: int = 10_000,
    memory_limit: str | None = None,
) -> Path:
    parquet_path = Path(parquet_path)
    database_path = Path(database_path)

    if not parquet_path.exists():
        raise FileNotFoundError(parquet_path)

    database_path.parent.mkdir(parents=True, exist_ok=True)

    con = connect(database_path, memory_limit=memory_limit)
    source = _sql_path(parquet_path)

    try:
        con.execute("DROP VIEW IF EXISTS storage_detail")
        con.execute(
            f"""
            CREATE VIEW storage_detail AS
            SELECT *
            FROM read_parquet('{source}')
            """
        )

        for table in (
            "data_quality",
            "folder_summary",
            "owner_summary",
            "category_summary",
            "simulation_summary",
            "stale_files",
            "largest_files",
        ):
            con.execute(f"DROP TABLE IF EXISTS {table}")

        con.execute(
            """
            CREATE TABLE data_quality AS
            SELECT
                COUNT(*) AS total_rows,
                COUNT(DISTINCT FullPath) AS distinct_paths,
                COUNT(*) - COUNT(DISTINCT FullPath) AS duplicate_path_rows,
                COUNT(*) FILTER (
                    WHERE FullPath IS NULL OR FullPath = ''
                ) AS missing_paths,
                COUNT(*) FILTER (WHERE ItemType = 'File') AS file_count,
                COUNT(*) FILTER (WHERE ItemType = 'Folder') AS folder_count,
                COUNT(*) FILTER (
                    WHERE ItemType = 'File'
                      AND (SizeGB IS NULL OR SizeGB < 0)
                ) AS invalid_file_sizes,
                SUM(SizeGB) FILTER (WHERE ItemType = 'File') AS total_file_storage_gb,
                COUNT(*) FILTER (
                    WHERE LastModified IS NULL OR LastModified = ''
                ) AS missing_modified_dates,
                COUNT(*) FILTER (
                    WHERE LastModified IS NOT NULL
                      AND LastModified <> ''
                      AND TRY_CAST(LastModified AS TIMESTAMP) IS NULL
                ) AS invalid_modified_dates
            FROM storage_detail
            """
        )

        con.execute(
            """
            CREATE TABLE category_summary AS
            SELECT
                Drive,
                FileCategory,
                COUNT(*) AS file_count,
                SUM(SizeGB) AS storage_gb,
                SUM(SizeGB) / 1024.0 AS storage_tb,
                SUM(
                    CASE
                        WHEN IsSimulationFile = 'Yes' THEN SizeGB
                        ELSE 0
                    END
                ) AS simulation_storage_gb
            FROM storage_detail
            WHERE ItemType = 'File'
            GROUP BY Drive, FileCategory
            ORDER BY storage_gb DESC
            """
        )

        con.execute(
            """
            CREATE TABLE owner_summary AS
            SELECT
                Owner,
                COUNT(*) AS file_count,
                SUM(SizeGB) AS storage_gb,
                SUM(SizeGB) / 1024.0 AS storage_tb,
                COUNT(*) FILTER (
                    WHERE IsSimulationFile = 'Yes'
                ) AS simulation_file_count,
                SUM(
                    CASE
                        WHEN IsSimulationFile = 'Yes' THEN SizeGB
                        ELSE 0
                    END
                ) AS simulation_storage_gb
            FROM storage_detail
            WHERE ItemType = 'File'
            GROUP BY Owner
            ORDER BY storage_gb DESC
            """
        )

        con.execute(
            """
            CREATE TABLE simulation_summary AS
            SELECT
                Drive,
                FileCategory,
                CASE
                    WHEN age_days IS NULL THEN 'Unknown'
                    WHEN age_days < 30 THEN '<30d'
                    WHEN age_days < 90 THEN '30-89d'
                    WHEN age_days < 365 THEN '90-364d'
                    WHEN age_days < 730 THEN '1-2y'
                    ELSE '2y+'
                END AS age_bucket,
                COUNT(*) AS file_count,
                SUM(SizeGB) AS storage_gb
            FROM (
                SELECT
                    *,
                    date_diff(
                        'day',
                        TRY_CAST(LastModified AS TIMESTAMP),
                        current_timestamp
                    ) AS age_days
                FROM storage_detail
                WHERE ItemType = 'File'
                  AND IsSimulationFile = 'Yes'
            )
            GROUP BY Drive, FileCategory, age_bucket
            ORDER BY storage_gb DESC
            """
        )

        con.execute(
            f"""
            CREATE TABLE stale_files AS
            SELECT
                Drive,
                ItemName,
                FileExtension,
                FullPath,
                Owner,
                SizeGB,
                FileCategory,
                LastModified,
                date_diff(
                    'day',
                    TRY_CAST(LastModified AS TIMESTAMP),
                    current_timestamp
                ) AS age_days,
                IsSimulationFile
            FROM storage_detail
            WHERE ItemType = 'File'
              AND LastModified IS NOT NULL
              AND date_diff(
                    'day',
                    TRY_CAST(LastModified AS TIMESTAMP),
                    current_timestamp
                  ) >= {int(stale_days)}
            ORDER BY SizeGB DESC
            LIMIT {int(largest_file_limit)}
            """
        )

        con.execute(
            f"""
            CREATE TABLE largest_files AS
            SELECT
                Drive,
                ItemName,
                FileExtension,
                FullPath,
                Owner,
                SizeGB,
                FileCategory,
                LastModified,
                IsSimulationFile,
                Depth,
                L1_Name,
                L2_Name,
                L3_Name,
                L4_Name
            FROM storage_detail
            WHERE ItemType = 'File'
            ORDER BY SizeGB DESC
            LIMIT {int(largest_file_limit)}
            """
        )

        con.execute(
            """
            CREATE TABLE folder_summary AS
            SELECT
                Drive,
                L1_Name,
                L2_Name,
                L3_Name,
                L4_Name,
                FileCategory,
                CASE
                    WHEN age_days IS NULL THEN 'Unknown'
                    WHEN age_days < 30 THEN '<30d'
                    WHEN age_days < 90 THEN '30-89d'
                    WHEN age_days < 365 THEN '90-364d'
                    WHEN age_days < 730 THEN '1-2y'
                    ELSE '2y+'
                END AS age_bucket,
                COUNT(*) AS file_count,
                SUM(SizeGB) AS storage_gb,
                SUM(SizeGB) / 1024.0 AS storage_tb,
                SUM(
                    CASE
                        WHEN IsSimulationFile = 'Yes' THEN SizeGB
                        ELSE 0
                    END
                ) AS simulation_storage_gb
            FROM (
                SELECT
                    *,
                    date_diff(
                        'day',
                        TRY_CAST(LastModified AS TIMESTAMP),
                        current_timestamp
                    ) AS age_days
                FROM storage_detail
                WHERE ItemType = 'File'
            )
            GROUP BY
                Drive,
                L1_Name,
                L2_Name,
                L3_Name,
                L4_Name,
                FileCategory,
                age_bucket
            ORDER BY storage_gb DESC
            """
        )
    finally:
        con.close()

    return database_path


def export_summary_tables(
    database_path: Path,
    output_dir: Path,
    formats: tuple[str, ...] = ("csv",),
) -> list[Path]:
    database_path = Path(database_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    con = connect(database_path)
    tables = [
        "data_quality",
        "folder_summary",
        "owner_summary",
        "category_summary",
        "simulation_summary",
        "stale_files",
        "largest_files",
    ]
    outputs = []

    try:
        for table in tables:
            for fmt in formats:
                output = output_dir / f"{table}.{fmt}"
                target = _sql_path(output)

                if fmt == "csv":
                    con.execute(
                        f"COPY {table} TO '{target}' "
                        "(FORMAT CSV, HEADER TRUE)"
                    )
                elif fmt == "parquet":
                    con.execute(
                        f"COPY {table} TO '{target}' "
                        "(FORMAT PARQUET, COMPRESSION ZSTD)"
                    )
                else:
                    raise ValueError(f"Unsupported export format: {fmt}")

                outputs.append(output)
    finally:
        con.close()

    return outputs
