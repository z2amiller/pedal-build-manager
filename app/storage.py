from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_VERSION_RE = re.compile(r"^[0-9a-z.-]+$")

_DEFAULT_DATA_DIR = "./data/boards"


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Invalid board slug: {slug!r}")


def _validate_version(version: str) -> None:
    if not _VERSION_RE.match(version):
        raise ValueError(f"Invalid version: {version!r}")


class BoardStore:
    def __init__(self, data_dir: Optional[str] = None) -> None:
        root = (
            data_dir
            if data_dir is not None
            else os.environ.get("BUILDER_DATA_DIR", _DEFAULT_DATA_DIR)
        )
        self._root = Path(root)

    def board_path(self, slug: str, version: str) -> Path:
        _validate_slug(slug)
        _validate_version(version)
        return self._root / slug / version

    def manifest_path(self, slug: str, version: str) -> Path:
        return self.board_path(slug, version) / "manifest.json"

    def zip_path(self, slug: str, version: str) -> Path:
        return self.board_path(slug, version) / "manifest.zip"

    def list_boards(self) -> List[str]:
        if not self._root.is_dir():
            return []
        return sorted(p.name for p in self._root.iterdir() if p.is_dir())

    def list_versions(self, slug: str) -> List[str]:
        _validate_slug(slug)
        board_dir = self._root / slug
        if not board_dir.is_dir():
            return []
        return sorted(p.name for p in board_dir.iterdir() if p.is_dir())
