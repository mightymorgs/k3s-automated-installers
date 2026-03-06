"""Template discovery for a single app directory."""

from __future__ import annotations

from pathlib import Path


def discover_app_templates(app_id: str, repo_path: Path) -> list[Path]:
    """Discover all .j2 files for a given app (templates, values, config, install)."""
    repo_path = Path(repo_path)
    app_dir = repo_path / "apps" / app_id
    if not app_dir.exists():
        return []

    templates: list[Path] = []
    for subdir in ("values", "templates", "config", "install"):
        scan_dir = app_dir / subdir
        if scan_dir.is_dir():
            templates.extend(sorted(scan_dir.glob("*.j2")))

    return sorted(templates)
