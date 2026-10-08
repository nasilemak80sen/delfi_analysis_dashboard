from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os


CSV_HEADERS = [
    "Drive",
    "ItemID",
    "ParentID",
    "ItemType",
    "ItemName",
    "FileExtension",
    "FullPath",
    "Depth",
    "Owner",
    "SizeMB",
    "SizeGB",
    "FileCountInFolder",
    "LastModified",
    "IsSimulationFile",
    "FileCategory",
    "ScanDateTime",
]

HIERARCHY_LEVELS = 10
CSV_HEADERS.extend([f"L{i}_Name" for i in range(1, HIERARCHY_LEVELS + 1)])

DEFAULT_ROOT_FOLDERS = [r"X:\Reservoir Engineering"]
DEFAULT_OUTPUT_PATH = (
    Path.home() / "Documents" / "crawler_result" / "STORAGE_ANALYSIS.csv"
)


@dataclass(slots=True)
class CrawlerConfig:
    root_folders: list[Path] = field(
        default_factory=lambda: [Path(p) for p in DEFAULT_ROOT_FOLDERS]
    )
    output_path: Path = DEFAULT_OUTPUT_PATH
    max_depth: int = 5
    skip_owner_info: bool = False
    hierarchy_levels: int = HIERARCHY_LEVELS
    debug: bool = False
    parquet_path: Path | None = None

    @classmethod
    def from_values(
        cls,
        root_folders: list[str] | None = None,
        output_path: str | None = None,
        max_depth: int = 5,
        skip_owner_info: bool = False,
        hierarchy_levels: int = HIERARCHY_LEVELS,
        debug: bool = False,
        parquet_path: str | None = None,
    ) -> "CrawlerConfig":
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if hierarchy_levels <= 0:
            raise ValueError("hierarchy_levels must be > 0")

        roots = [Path(p) for p in (root_folders or DEFAULT_ROOT_FOLDERS)]
        output = Path(output_path) if output_path else DEFAULT_OUTPUT_PATH
        parquet = Path(parquet_path) if parquet_path else None

        return cls(
            root_folders=roots,
            output_path=output,
            max_depth=max_depth,
            skip_owner_info=skip_owner_info,
            hierarchy_levels=hierarchy_levels,
            debug=debug,
            parquet_path=parquet,
        )


def normalize_path(path: str | os.PathLike[str]) -> str:
    """Normalise a Windows path without changing its case."""
    value = os.path.normpath(os.fspath(path))
    if value.endswith("\\") and len(value) > 3:
        value = value.rstrip("\\")
    return value


def drive_name(root: Path) -> str:
    """Return X: for mapped drives; otherwise use the UNC/share root."""
    drv = root.drive
    if drv:
        return drv
    parts = root.parts
    return parts[1] if len(parts) > 1 and parts[0].startswith("\\") else root.anchor
