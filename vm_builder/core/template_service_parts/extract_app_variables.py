"""Merged Jinja2 variable extraction for an app."""

from __future__ import annotations

from pathlib import Path

from vm_builder.core.template_service_parts.discover_app_templates import (
    discover_app_templates,
)
from vm_builder.core.template_service_parts.extract_jinja2_variables import (
    extract_jinja2_variables,
)


def extract_app_variables(app_id: str, repo_path: Path) -> dict[str, dict]:
    """Extract and merge variables across all templates for an app."""
    templates = discover_app_templates(app_id, repo_path)
    if not templates:
        return {}

    merged: dict[str, dict] = {}
    for template_path in templates:
        variables = extract_jinja2_variables(template_path)
        for name, metadata in variables.items():
            if name not in merged:
                entry = dict(metadata)
                entry["source_files"] = [metadata["source_file"]]
                entry.pop("source_file", None)
                merged[name] = entry
                continue

            existing = merged[name]
            source_file = metadata.get("source_file", "")
            if source_file and source_file not in existing.get("source_files", []):
                existing.setdefault("source_files", []).append(source_file)
            if "default" not in existing and "default" in metadata:
                existing["default"] = metadata["default"]

    return merged
