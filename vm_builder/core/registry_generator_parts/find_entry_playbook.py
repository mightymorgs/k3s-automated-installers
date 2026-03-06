"""Entry-playbook discovery for an app directory."""

from __future__ import annotations

from pathlib import Path


def find_entry_playbook(app_dir: Path) -> Path | None:
    """Find the app entrypoint playbook (01-*.yml).

    Prefers ``01-deploy.yml`` when multiple candidates exist
    (e.g. alongside ``01-apply-kustomize.yml``).  Results are
    sorted so the selection is deterministic across platforms.
    """
    install_dir = app_dir / "install"
    if install_dir.exists():
        deploy_files = sorted(install_dir.glob("01-*.yml"))
        if deploy_files:
            # Prefer 01-deploy.yml over 01-apply-kustomize.yml etc.
            for f in deploy_files:
                if f.name == "01-deploy.yml":
                    return f
            return deploy_files[0]

    deploy_files = sorted(app_dir.glob("01-*.yml"))
    if deploy_files:
        return deploy_files[0]

    deploy_files = sorted(app_dir.glob("**/install/01-*.yml"))
    if deploy_files:
        return deploy_files[0]

    deploy_files = sorted(app_dir.glob("**/01-*.yml"))
    if deploy_files:
        return deploy_files[0]

    return None
