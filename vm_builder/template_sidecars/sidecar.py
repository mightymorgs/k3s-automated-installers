"""Phase-level sidecar payload construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vm_builder.template_sidecars.detect_template import detect_template_refs
from vm_builder.template_sidecars.detect_uri import (
    detect_requires_apps,
    detect_service_refs,
    detect_uri_calls,
)
from vm_builder.template_sidecars.detect_wiring import detect_wiring
from vm_builder.template_sidecars.metadata import parse_playbook_metadata
from vm_builder.template_sidecars.summarize import summarize_file_entry


def build_phase_sidecar(
    phase_dir: Path,
    repo_id: str = "vm-builder-templates",
) -> dict[str, Any] | None:
    """Build one ``.idi-meta.yaml`` payload for a phase directory."""
    files_meta: dict[str, dict[str, Any]] = {}

    for file_path in sorted(phase_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.name.startswith("."):
            continue
        if file_path.suffix not in (".yml", ".yaml", ".j2"):
            continue

        rel_name = str(file_path.relative_to(phase_dir))
        metadata = None
        if file_path.suffix in (".yml", ".yaml"):
            metadata = parse_playbook_metadata(file_path)

        file_entry = summarize_file_entry(file_path, metadata=metadata)

        if file_path.suffix in (".yml", ".yaml"):
            uri_calls = detect_uri_calls(file_path)
            if uri_calls:
                file_entry["calls_api"] = uri_calls

            template_refs = detect_template_refs(file_path)
            if template_refs:
                file_entry["uses_files"] = template_refs

            wiring = detect_wiring(file_path, metadata=metadata)
            if wiring["reads_from"] or wiring["writes_to"]:
                file_entry["wiring"] = wiring

            requires = detect_requires_apps(file_path)
            if requires:
                file_entry["requires_apps"] = requires

            svc_refs = detect_service_refs(file_path)
            if svc_refs:
                file_entry["references_services"] = svc_refs

        files_meta[rel_name] = file_entry

    if not files_meta:
        return None

    # Aggregate phase-level depends_on from all files
    phase_deps: set[str] = set()
    for finfo in files_meta.values():
        for app in finfo.get("requires_apps", []):
            phase_deps.add(app)
        for svc in finfo.get("references_services", []):
            phase_deps.add(svc)

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "repo_id": repo_id,
        "files": files_meta,
    }
    if phase_deps:
        result["depends_on_apps"] = sorted(phase_deps)

    return result
