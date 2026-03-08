"""Install delta computation for AppInstallService."""

from __future__ import annotations


def compute_install_delta(self, existing_apps: list[str], requested_apps: list[str]) -> list[str]:
    """Compute which apps need to be installed."""
    if not requested_apps:
        return []

    union = list(set(existing_apps + requested_apps))
    resolved = self._registry.resolve_deps(union)
    existing_set = set(existing_apps)
    return [app for app in resolved if app not in existing_set]
