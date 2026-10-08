from __future__ import annotations

import os
from pathlib import Path


def relative_parts(root: Path, item: Path) -> tuple[str, ...]:
    """Return the item's path below root as hierarchy segments."""
    relative = os.path.relpath(item, root)
    if relative in (".", ""):
        return ()
    return tuple(part for part in Path(relative).parts if part not in (".", ""))


def depth_from_hierarchy(hierarchy: tuple[str, ...]) -> int:
    return len(hierarchy)


def parent_path(path: Path) -> Path:
    return Path(os.path.dirname(os.fspath(path)))


def normalised_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(os.fspath(path)))
