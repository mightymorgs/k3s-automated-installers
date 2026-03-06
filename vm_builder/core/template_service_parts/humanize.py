"""Humanization helper for template variable labels."""

from __future__ import annotations


def humanize(name: str) -> str:
    """Turn a snake_case field name into a title label."""
    return name.replace("_", " ").title()
