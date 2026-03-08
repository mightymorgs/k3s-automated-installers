"""Playbook metadata extraction helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def extract_playbook_metadata(file_path: Path) -> dict[str, Any] | None:
    """Extract top-of-file # playbook_metadata YAML block."""
    content = file_path.read_text()

    metadata_lines: list[str] = []
    in_metadata = False
    for line in content.split("\n"):
        if "# playbook_metadata:" in line:
            in_metadata = True
            metadata_lines.append("playbook_metadata:")
            continue
        if in_metadata:
            if not line.startswith("#"):
                break
            stripped = line.lstrip("#").rstrip()
            if stripped:
                metadata_lines.append(stripped)

    if not metadata_lines:
        return None

    try:
        metadata_yaml = "\n".join(metadata_lines)
        parsed = yaml.safe_load(metadata_yaml)
        return parsed.get("playbook_metadata", {})
    except yaml.YAMLError:
        return None
