"""App-level sidecar generation."""

from __future__ import annotations

from pathlib import Path

import yaml

from vm_builder.template_sidecars.phase import iter_phase_dirs
from vm_builder.template_sidecars.sidecar import build_phase_sidecar


def generate_sidecar_for_app(
    app_dir: Path,
    repo_id: str = "vm-builder-templates",
) -> int:
    """Generate ``.idi-meta.yaml`` files for all phase dirs in one app."""
    count = 0

    for phase_dir in iter_phase_dirs(app_dir):
        sidecar = build_phase_sidecar(phase_dir=phase_dir, repo_id=repo_id)
        if sidecar is None:
            continue

        sidecar_path = phase_dir / ".idi-meta.yaml"
        sidecar_path.write_text(
            yaml.dump(sidecar, default_flow_style=False, sort_keys=False)
        )
        count += 1

    return count

