"""Playbook metadata extraction for template sidecar generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def parse_playbook_metadata(playbook_path: Path) -> dict[str, Any] | None:
    """Extract ``playbook_metadata`` from top-of-file comment blocks.

    Supports files that begin with ``---`` and nested section comment
    headers within the metadata block.
    """
    content = playbook_path.read_text()
    lines = content.split("\n")

    meta_lines: list[str] = []
    in_meta = False

    for line in lines:
        stripped = line.strip()

        if stripped == "# playbook_metadata:":
            in_meta = True
            continue

        if not in_meta:
            continue

        if line.startswith("#   ") or line.startswith("#\t"):
            raw = line[1:]  # remove leading '#'
            if raw.strip().startswith("# "):
                # Ignore section header comments inside metadata.
                continue
            meta_lines.append(raw)
            continue

        if stripped == "#":
            meta_lines.append("")
            continue

        # Any non-comment line ends metadata block.
        break

    if not meta_lines:
        return None

    try:
        parsed = yaml.safe_load("\n".join(meta_lines))
    except yaml.YAMLError:
        return None

    if isinstance(parsed, dict):
        return parsed
    return None

