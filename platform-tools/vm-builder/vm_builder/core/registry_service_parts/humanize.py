"""Field-label helper for RegistryService variable derivation."""

from __future__ import annotations


def humanize(field_name: str) -> str:
    """Turn a snake_case field name into a human-readable label."""
    return field_name.replace("_", " ").title()
