"""Per-app config lifecycle API routes.

Manages _config and _overrides in the BWS inventory, allowing
individual field PATCH, full config GET, and reset-to-default.

Delegates to ConfigService for business logic.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import APIRouter

from vm_builder.api.deps import get_vm_service
from vm_builder.core.config_service import ConfigService
from vm_builder.core.models import AppConfigResponse, ConfigUpdateRequest

router = APIRouter(prefix="/api/v1", tags=["vm-config"])


def _templates_dir() -> Path | None:
    """Resolve the templates directory from environment."""
    raw = os.environ.get("TEMPLATES_DIR")
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    return None


def _get_config_service() -> ConfigService:
    """Build a ConfigService with current dependencies."""
    return ConfigService(
        vm_service=get_vm_service(),
        templates_dir=_templates_dir(),
    )


@router.get("/vms/{vm_name}/apps/{app_id}/config")
async def get_app_config(vm_name: str, app_id: str):
    """Return the full config state for an app: config, overrides, defaults."""
    svc = _get_config_service()
    result = await asyncio.to_thread(
        svc.get_app_config, vm_name, app_id, svc._templates_dir,
    )
    return AppConfigResponse(**result).model_dump()


@router.patch("/vms/{vm_name}/apps/{app_id}/config")
async def update_config_field(
    vm_name: str,
    app_id: str,
    body: ConfigUpdateRequest,
):
    """Update a single config field for an app and track as override."""
    svc = _get_config_service()
    return await asyncio.to_thread(
        svc.update_field, vm_name, app_id, body.field, body.value,
    )


@router.delete("/vms/{vm_name}/apps/{app_id}/config/{field_name}")
async def reset_config_field(vm_name: str, app_id: str, field_name: str):
    """Reset a single config field to its template default."""
    svc = _get_config_service()
    return await asyncio.to_thread(
        svc.reset_field, vm_name, app_id, field_name, svc._templates_dir,
    )


@router.post("/vms/{vm_name}/apps/{app_id}/preview")
async def preview_config_changes(vm_name: str, app_id: str):
    """Render J2 templates with current _config and diff against k8s-base."""
    svc = _get_config_service()
    return await asyncio.to_thread(
        svc.preview_changes, vm_name, app_id, svc._templates_dir,
    )


@router.post("/vms/{vm_name}/apps/{app_id}/apply")
async def apply_config_live(
    vm_name: str,
    app_id: str,
    dry_run: bool = False,
):
    """Apply rendered config to the live VM via kubectl over SSH."""
    svc = _get_config_service()
    return await asyncio.to_thread(
        svc.apply_live, vm_name, app_id, svc._templates_dir, dry_run,
    )
