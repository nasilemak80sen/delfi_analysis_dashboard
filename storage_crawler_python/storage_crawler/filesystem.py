from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .classifier import get_file_category, is_simulation_file
from .config import CrawlerConfig, drive_name, normalize_path
from .hierarchy import normalised_key, parent_path, relative_parts
from .models import ScanRecord, ScanSummary
from .owner import OwnerResolver

logger = logging.getLogger(__name__)


def _is_excluded_path(path: Path, config: CrawlerConfig) -> bool:
    """Prevent the crawler from ingesting files it is actively producing."""
    key = os.path.normcase(os.path.normpath(os.fspath(path)))
    excluded = {os.path.normcase(os.path.normpath(os.fspath(p))) for p in (config.output_path, config.parquet_path) if p}
    return key in excluded


@dataclass
class ScanContext:
    config: CrawlerConfig
    owner_resolver: OwnerResolver
    summary: ScanSummary
    next_item_id: int = 0
    scan_datetime: datetime = None

    def __post_init__(self) -> None:
        if self.scan_datetime is None:
            self.scan_datetime = datetime.now()

    def allocate_item_id(self) -> int:
        self.next_item_id += 1
        return self.next_item_id


def _safe_last_modified(path: Path, stat_result: os.stat_result | None = None) -> datetime:
    try:
        stat_value = stat_result or path.stat()
        return datetime.fromtimestamp(stat_value.st_mtime)
    except OSError:
        return datetime.fromtimestamp(0)


def _safe_file_stat(entry: os.DirEntry[str]) -> os.stat_result | None:
    try:
        return entry.stat(follow_symlinks=False)
    except OSError:
        return None


def _emit_file(
    *,
    context: ScanContext,
    emit: Callable[[ScanRecord], None],
    root: Path,
    path: Path,
    parent_id: int,
    hierarchy: tuple[str, ...],
) -> float:
    stat_result = None
    try:
        stat_result = path.stat(follow_symlinks=False)
    except OSError:
        context.summary.inaccessible_paths += 1
        logger.warning("Could not stat file: %s", path)
        return 0.0

    size_gb = stat_result.st_size / (1024 ** 3)
    size_mb = stat_result.st_size / (1024 ** 2)
    depth = len(hierarchy)
    extension = path.suffix
    sim_file = is_simulation_file(extension)
    category = get_file_category(extension)
    owner = context.owner_resolver.get(path, parent_path(path), depth)

    item_id = context.allocate_item_id()

    record = ScanRecord(
        drive=drive_name(root),
        item_id=item_id,
        parent_id=parent_id,
        item_type="File",
        item_name=path.name,
        file_extension=extension,
        full_path=normalize_path(path),
        depth=depth,
        owner=owner,
        size_mb=size_mb,
        size_gb=size_gb,
        file_count_in_folder=0,
        last_modified=_safe_last_modified(path, stat_result),
        is_simulation_file=sim_file,
        file_category=category,
        scan_datetime=context.scan_datetime,
        hierarchy=hierarchy,
    )

    emit(record)
    context.summary.absorb_file(size_gb, sim_file == "Yes", depth)
    return size_gb


def _scan_directory(
    *,
    context: ScanContext,
    emit: Callable[[ScanRecord], None],
    root: Path,
    directory: Path,
    parent_id: int,
    hierarchy: tuple[str, ...],
    depth: int,
) -> float:
    """
    Scan a directory using os.scandir.

    The folder itself receives an ItemID before recursion so descendants
    can reference it through ParentID. Its CSV row is emitted after children
    have been traversed because its total size is then known.
    """
    item_id = context.allocate_item_id()
    owner = context.owner_resolver.get(
        directory,
        parent_path(directory),
        depth,
    )
    context.owner_resolver.register_folder_owner(directory, owner)

    total_size_gb = 0.0
    direct_file_count = 0

    try:
        with os.scandir(directory) as entries:
            entries_list = list(entries)
    except OSError:
        context.summary.inaccessible_paths += 1
        logger.warning("Could not enumerate directory: %s", directory)
        entries_list = []

    # Deterministic Python ordering improves reproducibility.
    entries_list.sort(key=lambda e: e.name.casefold())

    for entry in entries_list:
        child = Path(entry.path)

        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            context.summary.inaccessible_paths += 1
            logger.warning("Could not inspect: %s", child)
            continue

        child_hierarchy = hierarchy + (entry.name,)

        if is_dir:
            # MaxDepth is enforced BEFORE recursing.
            if depth < context.config.max_depth:
                total_size_gb += _scan_directory(
                    context=context,
                    emit=emit,
                    root=root,
                    directory=child,
                    parent_id=item_id,
                    hierarchy=child_hierarchy,
                    depth=depth + 1,
                )
            continue

        # A file under a folder at max depth would be one level deeper,
        # so it must not be emitted.
        if depth >= context.config.max_depth:
            continue

        if _is_excluded_path(child, context.config):
            logger.debug("Excluded output path from scan: %s", child)
            continue

        total_size_gb += _emit_file(
            context=context,
            emit=emit,
            root=root,
            path=child,
            parent_id=item_id,
            hierarchy=child_hierarchy,
        )
        direct_file_count += 1

    context.summary.absorb_folder(depth)

    record = ScanRecord(
        drive=drive_name(root),
        item_id=item_id,
        parent_id=parent_id,
        item_type="Folder",
        item_name=directory.name,
        file_extension="",
        full_path=normalize_path(directory),
        depth=depth,
        owner=owner,
        size_mb=total_size_gb * 1024,
        size_gb=total_size_gb,
        file_count_in_folder=direct_file_count,
        last_modified=_safe_last_modified(directory),
        is_simulation_file="N/A",
        file_category="N/A",
        scan_datetime=context.scan_datetime,
        hierarchy=hierarchy,
    )
    emit(record)
    return total_size_gb


def scan_root(
    root: Path,
    context: ScanContext,
    emit: Callable[[ScanRecord], None],
) -> bool:
    """
    Scan below a root folder.

    The root itself is deliberately not emitted as a row, matching
    Get-ChildItem -Recurse in the existing PowerShell crawler.
    """
    root = Path(root)

    if not root.exists() or not root.is_dir():
        logger.warning("SKIP: '%s' not found or is not a directory", root)
        return False

    try:
        with os.scandir(root) as entries:
            entries_list = list(entries)
    except OSError:
        context.summary.inaccessible_paths += 1
        logger.warning("Could not enumerate root: %s", root)
        return False

    entries_list.sort(key=lambda e: e.name.casefold())

    context.summary.roots_scanned += 1

    for entry in entries_list:
        child = Path(entry.path)
        hierarchy = (entry.name,)

        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            context.summary.inaccessible_paths += 1
            logger.warning("Could not inspect: %s", child)
            continue

        if is_dir:
            if context.config.max_depth >= 1 and not _is_excluded_path(child, context.config):
                _scan_directory(
                    context=context,
                    emit=emit,
                    root=root,
                    directory=child,
                    parent_id=0,
                    hierarchy=hierarchy,
                    depth=1,
                )
        else:
            if context.config.max_depth >= 1 and not _is_excluded_path(child, context.config):
                _emit_file(
                    context=context,
                    emit=emit,
                    root=root,
                    path=child,
                    parent_id=0,
                    hierarchy=hierarchy,
                )

    return True


def run_scan(
    config: CrawlerConfig,
    emit: Callable[[ScanRecord], None],
) -> ScanSummary:
    summary = ScanSummary()
    context = ScanContext(
        config=config,
        owner_resolver=OwnerResolver(config.skip_owner_info),
        summary=summary,
    )

    for root in config.root_folders:
        scan_root(root, context, emit)

    return summary
