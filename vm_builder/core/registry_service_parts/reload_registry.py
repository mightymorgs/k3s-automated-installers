"""Registry cache reset for RegistryService."""

from __future__ import annotations


def reload_registry(self) -> None:
    """Force a reload from disk on the next read."""
    self._data = None
