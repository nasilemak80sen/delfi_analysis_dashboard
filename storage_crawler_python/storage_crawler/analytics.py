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

    parquet_path.parent.mkdir(parents=True, exist_ok=True)

    con = connect(memory_limit=memory_limit)
    try:
        source = _sql_path(csv_path)
        target = _sql_path(parquet_path)

        con.execute(
            f"""
            COPY (
                SELECT *
                FROM read_csv(
                    '{source}',
                    header = true,
                    delim = ',',
                    quote = '"',
                    escape = '"',
                    sample_size = -1,
                    union_by_name = true,
                    strict_mode = true,
                    null_padding = false
                )
            )
            TO '{target}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                ROW_GROUP_SIZE {int(row_group_size)}
            )
            """
        )
    finally:
        con.close()

    return parquet_path


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
                COUNT(*) FILTER (
                    WHERE LastModified IS NULL OR LastModified = ''
                ) AS missing_modified_dates
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
                        try_strptime(
                            LastModified,
                            '%Y-%m-%d %H:%M:%S'
                        ),
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
                    try_strptime(
                        LastModified,
                        '%Y-%m-%d %H:%M:%S'
                    ),
                    current_timestamp
                ) AS age_days,
                IsSimulationFile
            FROM storage_detail
            WHERE ItemType = 'File'
              AND try_strptime(
                    LastModified,
                    '%Y-%m-%d %H:%M:%S'
                  ) IS NOT NULL
              AND date_diff(
                    'day',
                    try_strptime(
                        LastModified,
                        '%Y-%m-%d %H:%M:%S'
                    ),
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
                        try_strptime(
                            LastModified,
                            '%Y-%m-%d %H:%M:%S'
                        ),
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
