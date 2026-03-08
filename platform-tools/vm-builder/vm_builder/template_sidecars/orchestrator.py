"""Batch orchestration for template sidecar generation."""

from __future__ import annotations

from pathlib import Path

from vm_builder.template_sidecars.app import generate_sidecar_for_app


def generate_all_sidecars(
    templates_dir: Path,
    repo_id: str = "vm-builder-templates",
) -> int:
    """Generate sidecars for all apps under ``templates_dir/apps``."""
    apps_dir = templates_dir / "apps"
    if not apps_dir.exists():
        print(f"No apps/ directory found in {templates_dir}")
        return 0

    total = 0
    app_dirs = sorted(directory for directory in apps_dir.iterdir() if directory.is_dir())

    for app_dir in app_dirs:
        count = generate_sidecar_for_app(app_dir, repo_id=repo_id)
        if count:
            print(f"  {app_dir.name}: {count} sidecar(s)")
        total += count

    return total

