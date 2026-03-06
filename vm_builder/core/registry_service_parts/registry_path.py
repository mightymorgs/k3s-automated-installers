"""Registry-path selector for RegistryService."""

from __future__ import annotations

from pathlib import Path


def registry_path(self) -> Path:
    """Return live registry path when available, otherwise baked-in path."""
    if self._live_path and self._live_path.exists():
        return self._live_path
    return self._path
