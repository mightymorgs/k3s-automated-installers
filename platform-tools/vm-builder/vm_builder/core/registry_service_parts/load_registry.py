"""Registry loader/cache for RegistryService."""

from __future__ import annotations

import json


def load_registry(self) -> dict:
    """Load and cache registry data from disk."""
    if self._data is None:
        path = self._registry_path()
        with open(path) as handle:
            self._data = json.load(handle)
    return self._data
