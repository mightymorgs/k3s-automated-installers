"""Source discovery helpers for VM Builder skill generation."""

from __future__ import annotations

from pathlib import Path


def iter_source_modules(source_root: Path) -> list[Path]:
    """Return candidate Python source modules for skill extraction.

    The legacy script scanned both:
    - ``<source_root>/core/*.py``
    - ``<source_root>/*.py``
    """
    modules: list[Path] = []

    core_dir = source_root / "core"
    if core_dir.exists():
        modules.extend(sorted(core_dir.glob("*.py")))

    if source_root.exists():
        modules.extend(sorted(source_root.glob("*.py")))

    return modules

