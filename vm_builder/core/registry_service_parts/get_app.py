"""Single-app lookup for RegistryService."""

from __future__ import annotations


def get_app(self, app_id: str) -> dict:
    """Return an app by id."""
    data = self._load()
    apps = data.get("apps", {})
    if app_id not in apps:
        raise KeyError(f"App not found: {app_id}")
    return self._enrich_app(app_id, apps[app_id])
