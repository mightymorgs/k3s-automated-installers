"""Phase directory traversal for template sidecar generation."""

from __future__ import annotations

from pathlib import Path

from vm_builder.template_sidecars.constants import PHASE_DIRS


def iter_phase_dirs(app_dir: Path) -> list[Path]:
    """Return sorted, valid phase directories under an app directory."""
    if not app_dir.exists():
        return []

    return sorted(
        directory
        for directory in app_dir.iterdir()
        if directory.is_dir() and directory.name in PHASE_DIRS
    )

