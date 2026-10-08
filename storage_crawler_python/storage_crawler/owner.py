from __future__ import annotations

import os
import subprocess
from pathlib import Path


class OwnerResolver:
    """
    Cached owner resolver.

    Behaviour mirrors the current PowerShell approach:
      - return cached owner when available
      - otherwise inherit a cached parent owner when available
      - for depth <= 3, query Get-Acl
      - for deeper items, inherit from the folder cache if possible
    """

    def __init__(self, skip_owner_info: bool = False, acl_depth: int = 3):
        self.skip_owner_info = skip_owner_info
        self.acl_depth = acl_depth
        self._cache: dict[str, str] = {}

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(os.path.normpath(os.fspath(path)))

    def get(
        self,
        path: Path,
        parent_path: Path | None,
        depth: int,
    ) -> str:
        if self.skip_owner_info:
            return ""

        key = self._key(path)
        if key in self._cache:
            return self._cache[key]

        owner = ""

        if parent_path is not None:
            parent_key = self._key(parent_path)
            if parent_key in self._cache:
                owner = self._cache[parent_key]
                self._cache[key] = owner
                return owner

        if depth <= self.acl_depth:
            owner = self._get_acl_owner(path)
        else:
            if parent_path is not None:
                parent_key = self._key(parent_path)
                owner = self._cache.get(parent_key, "")

        self._cache[key] = owner
        return owner

    def register_folder_owner(self, path: Path, owner: str) -> None:
        self._cache[self._key(path)] = owner

    def _get_acl_owner(self, path: Path) -> str:
        """
        Use Windows PowerShell Get-Acl instead of adding pywin32 just for owner lookup.
        The crawler still works cross-platform when owner lookup is skipped.
        """
        if os.name != "nt":
            return ""

        command = r"(Get-Acl -LiteralPath $args[0] -ErrorAction SilentlyContinue).Owner"

        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                    os.fspath(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return "Access Denied"

        value = completed.stdout.strip()
        return value if value else "Access Denied"
