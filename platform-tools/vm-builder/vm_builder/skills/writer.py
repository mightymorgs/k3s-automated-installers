"""Filesystem write helpers for VM Builder skill markdown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vm_builder.skills.markdown import render_skill_markdown
from vm_builder.skills.naming import skill_filename


def write_skill_file(
    operation: dict[str, Any],
    output_dir: Path,
    colliding_operations: set[str],
    service: str = "vm-builder",
) -> Path:
    """Write one operation skill file and return its path."""
    resource_dir = output_dir / str(operation["resource"])
    resource_dir.mkdir(parents=True, exist_ok=True)

    filename = skill_filename(operation, colliding_operations)
    skill_path = resource_dir / filename
    skill_path.write_text(render_skill_markdown(operation, service=service))
    return skill_path

