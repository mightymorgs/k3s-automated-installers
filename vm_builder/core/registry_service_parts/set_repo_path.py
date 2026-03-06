"""Repository-path setter for RegistryService."""

from __future__ import annotations

from pathlib import Path


def set_repo_path(self, path: Path) -> None:
    """Set cloned repository root for template scanning."""
    self._repo_path = Path(path)
