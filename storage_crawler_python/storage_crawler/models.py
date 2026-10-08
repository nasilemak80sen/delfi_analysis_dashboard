from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class ScanRecord:
    drive: str
    item_id: int
    parent_id: int
    item_type: str
    item_name: str
    file_extension: str
    full_path: str
    depth: int
    owner: str
    size_mb: float
    size_gb: float
    file_count_in_folder: int
    last_modified: datetime
    is_simulation_file: str
    file_category: str
    scan_datetime: datetime
    hierarchy: tuple[str, ...] = field(default_factory=tuple)

    def as_row(self, hierarchy_levels: int = 10) -> list[object]:
        row: list[object] = [
            self.drive,
            self.item_id,
            self.parent_id,
            self.item_type,
            self.item_name,
            self.file_extension,
            self.full_path,
            self.depth,
            self.owner,
            self.size_mb,
            self.size_gb,
            self.file_count_in_folder,
            self.last_modified.strftime("%Y-%m-%d %H:%M:%S"),
            self.is_simulation_file,
            self.file_category,
            self.scan_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        ]
        row.extend(self.hierarchy[:hierarchy_levels])
        row.extend([""] * max(0, hierarchy_levels - len(self.hierarchy)))
        return row


@dataclass(slots=True)
class ScanSummary:
    total_folders: int = 0
    total_files: int = 0
    max_depth_found: int = 0
    total_size_gb: float = 0.0
    simulation_file_count: int = 0
    inaccessible_paths: int = 0
    roots_scanned: int = 0

    @property
    def total_items(self) -> int:
        return self.total_folders + self.total_files

    @property
    def total_size_tb(self) -> float:
        return self.total_size_gb / 1024.0

    def absorb_file(self, size_gb: float, is_simulation: bool, depth: int) -> None:
        self.total_files += 1
        self.total_size_gb += size_gb
        self.max_depth_found = max(self.max_depth_found, depth)
        if is_simulation:
            self.simulation_file_count += 1

    def absorb_folder(self, depth: int) -> None:
        self.total_folders += 1
        self.max_depth_found = max(self.max_depth_found, depth)
