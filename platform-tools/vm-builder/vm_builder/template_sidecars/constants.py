"""Constants for VM Builder template sidecar generation."""

from __future__ import annotations

# Phase directories to scan for files.
PHASE_DIRS: frozenset[str] = frozenset(
    {
        "install",
        "config",
        "verify",
        "templates",
        "k8s-base",
        "k8s-standalone",
        "k8s-storage",
        "values",
        "operations",
        "render",
        "uninstall",
    }
)

