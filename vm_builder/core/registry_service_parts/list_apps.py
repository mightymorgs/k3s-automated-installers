"""App listing for RegistryService."""

from __future__ import annotations

from typing import Optional


def list_apps(self, category: Optional[str] = None) -> list[dict]:
    """List all apps, optionally filtered by category."""
    data = self._load()
    apps: list[dict] = []
    for app_id, app_data in data.get("apps", {}).items():
        if category and app_data.get("category") != category:
            continue
        apps.append(self._enrich_app(app_id, app_data))
    return apps
