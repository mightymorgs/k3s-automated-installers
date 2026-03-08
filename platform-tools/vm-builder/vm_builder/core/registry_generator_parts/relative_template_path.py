"""Relative-path helper with optional prefix for registry paths."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def relative_template_path(
    path: Path,
    templates_dir: Path,
    path_prefix: Optional[str] = None,
) -> str:
    """Convert a template path to registry-relative path with optional prefix."""
    relative = str(path.relative_to(templates_dir))
    if path_prefix:
        return f"{path_prefix}/{relative}"
    return relative
