"""File summarization helpers for template sidecar entries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_KIND_PATTERN = re.compile(r"^kind:\s*(\S+)", re.MULTILINE)


def _summary_for_yaml(file_path: Path, metadata: dict[str, Any] | None) -> str:
    """Build a summary for a YAML file."""
    if metadata:
        description = str(metadata.get("description", "")).strip()
        if description:
            return description
        return f"Playbook: {file_path.name}"

    content = file_path.read_text()

    if "kustomization" in file_path.name.lower():
        return f"Kustomization: {file_path.name}"

    if "kind:" in content:
        kind_match = _KIND_PATTERN.search(content)
        if kind_match:
            return f"K8s {kind_match.group(1)}: {file_path.name}"
        return f"Manifest: {file_path.name}"

    if "ansible.builtin" in content or "hosts:" in content:
        return f"Playbook: {file_path.name}"

    return f"Manifest: {file_path.name}"


def summarize_file_entry(
    file_path: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build base sidecar metadata for one file."""
    if file_path.suffix in (".yml", ".yaml"):
        summary = _summary_for_yaml(file_path, metadata)
    elif file_path.suffix == ".j2":
        summary = f"Jinja2 template: {file_path.name}"
    else:
        summary = f"File: {file_path.name}"

    return {
        "summary": summary,
        "source": "inferred",
        "confidence": "medium",
    }

