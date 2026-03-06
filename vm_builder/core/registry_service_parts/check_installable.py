"""Installability checks for RegistryService."""

from __future__ import annotations


def check_installable(self, app_id: str, installed_apps: list[str]) -> dict:
    """Check whether all dependencies for app_id are already installed."""
    all_deps = self.resolve_deps([app_id])
    deps_only = [dependency for dependency in all_deps if dependency != app_id]
    missing = [dependency for dependency in deps_only if dependency not in installed_apps]
    return {
        "installable": len(missing) == 0,
        "missing_deps": missing,
        "all_deps": all_deps,
    }
