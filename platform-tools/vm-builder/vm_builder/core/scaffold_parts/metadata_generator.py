"""Generate playbook metadata headers and .idi-meta.yaml sidecar stubs."""

from pathlib import Path
from typing import Optional

from vm_builder.core.scaffold_parts.playbook_generator import PlaybookConfig


def generate_metadata_header(
    config: PlaybookConfig,
    playbook_id: str,
    dependencies: Optional[list[str]] = None,
    provides: Optional[list[str]] = None,
    bws_state: Optional[list[str]] = None,
) -> str:
    """Generate a playbook metadata YAML comment block.

    Returns a string of ``#``-prefixed lines compatible with the existing
    golden-master playbook metadata convention.
    """
    lines = [
        "# playbook_metadata:",
        f"#   id: {playbook_id}",
        "#   type: atomic",
        "#",
        "#   path_info:",
        f"#     category: apps",
        f"#     subsystem: {config.app_name}",
    ]

    if dependencies:
        lines.append("#")
        lines.append("#   dependencies:")
        for dep in dependencies:
            lines.append(f"#     - {dep}")

    if provides:
        lines.append("#")
        lines.append("#   provides:")
        for p in provides:
            lines.append(f"#     - {p}")

    if config.credential_fields:
        lines.append("#")
        lines.append("#   credentials:")
        for cred in config.credential_fields:
            lines.append(f"#     - {cred}")

    if bws_state:
        lines.append("#")
        lines.append("#   bws_state:")
        for path in bws_state:
            lines.append(f"#     - {path}")

    return "\n".join(lines) + "\n"


def generate_sidecar(phase_dir: Path, app_name: str) -> dict:
    """Generate a ``.idi-meta.yaml`` sidecar dict for a phase directory.

    Scans for ``*.yml`` files in *phase_dir* and produces a stub entry for
    each, following the schema used by the existing sidecar generator.
    """
    files: dict[str, dict] = {}

    for yml_file in sorted(phase_dir.glob("*.yml")):
        files[yml_file.name] = {
            "summary": f"Auto-generated scaffold playbook for {app_name}",
            "source": "scaffold",
            "confidence": "low",
        }

    return {
        "schema_version": "1.0",
        "files": files,
    }
