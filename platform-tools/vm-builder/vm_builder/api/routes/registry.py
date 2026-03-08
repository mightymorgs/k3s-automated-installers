"""App registry API routes."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from vm_builder.api.deps import get_registry_service, get_repo_service, set_repo_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/registry", tags=["registry"])


class ResolveRequest(BaseModel):
    selected_apps: list[str]


@router.get("/apps")
async def list_apps(category: Optional[str] = Query(None)):
    svc = get_registry_service()
    return svc.list_apps(category=category)


@router.get("/apps/{app_id}")
async def get_app(app_id: str):
    svc = get_registry_service()
    try:
        return svc.get_app(app_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/resolve-deps")
async def resolve_deps(body: ResolveRequest):
    svc = get_registry_service()
    try:
        resolved = svc.resolve_deps(body.selected_apps)
    except KeyError as e:
        raise HTTPException(400, str(e))
    return {"resolved": resolved}


@router.post("/generate")
async def generate_registry():
    """Regenerate the app registry from templates on disk."""
    svc = get_registry_service()
    try:
        registry = svc.generate()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    app_count = len(registry.get("apps", {}))
    return {"status": "ok", "app_count": app_count}


@router.post("/refresh")
async def refresh_registry():
    """Pull latest from git repo and regenerate the app registry.

    This is the primary mechanism for updating the tool with newly
    created playbooks. It:
    1. Pulls latest changes from the cloned enterprise repo.
    2. Regenerates the registry from the repo's templates directory.
    3. Falls back to the configured TEMPLATES_DIR if the repo has no templates.

    Returns:
        JSON with repo sync status and registry app count.
    """
    from vm_builder.api.app import reload_bws_config  # lazy to avoid circular import
    reload_bws_config()

    repo_svc = get_repo_service()
    registry_svc = get_registry_service()

    # Step 1: Pull latest from git
    repo_status = repo_svc.ensure_repo()
    set_repo_status(repo_status)

    if not repo_status.available:
        hint = "Complete initial setup at /init and sync the repository"
        detail = repo_status.error or "Repo sync failed"
        raise HTTPException(503, f"{detail} — {hint}")

    # Step 2: Regenerate registry from repo templates (or fallback)
    repo_templates = repo_svc.get_templates_dir()
    try:
        if repo_templates:
            logger.info("Refreshing registry from repo templates: %s", repo_templates)
            registry = registry_svc.refresh(repo_templates)
        else:
            logger.info("No templates in repo, regenerating from configured TEMPLATES_DIR")
            registry = registry_svc.generate()
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    app_count = len(registry.get("apps", {}))
    return {
        "status": "ok",
        "repo": {
            "action": repo_status.action,
            "repo_dir": repo_status.repo_dir,
        },
        "registry": {
            "app_count": app_count,
            "source": "repo" if repo_templates else "local",
        },
    }


@router.get("/apps/{app_id}/installable")
async def check_installable(app_id: str, installed: str = Query("")):
    """Check if an app can be installed given currently installed apps.

    The ``installed`` query param is a comma-separated list of app_ids
    already installed on the target VM.
    """
    svc = get_registry_service()
    installed_list = [a.strip() for a in installed.split(",") if a.strip()]
    try:
        result = svc.check_installable(app_id, installed_list)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return result
