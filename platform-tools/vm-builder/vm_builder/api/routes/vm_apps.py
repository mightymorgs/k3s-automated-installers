"""VM app management API routes -- install, list, uninstall apps on running VMs."""

import asyncio
import logging
from fastapi import APIRouter
from vm_builder.api.deps import get_app_install_service
from vm_builder.core.models import BatchAppInstallRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["vm-apps"])


@router.get("/vms/{vm_name}/apps")
async def list_installed_apps(vm_name: str):
    """List apps installed on a VM with their current status."""
    svc = get_app_install_service()
    apps = await asyncio.to_thread(svc.list_installed_apps, vm_name)
    return [a.model_dump() for a in apps]


@router.post("/vms/{vm_name}/apps")
async def install_apps(vm_name: str, body: BatchAppInstallRequest):
    """Install app(s) on a running VM.

    Resolves dependencies server-side, computes the install delta
    (requested + deps minus already-installed), and triggers
    install/configure workflows in dependency order.
    """
    svc = get_app_install_service()
    result = await asyncio.to_thread(svc.install_apps, vm_name, body)
    return result.model_dump()


@router.delete("/vms/{vm_name}/apps/{app_id}")
async def uninstall_app(vm_name: str, app_id: str):
    """Remove an app from the VM's inventory.

    Only removes from BWS inventory (selected_apps and _state).
    K8s resources (Helm releases, PVCs, secrets) are NOT deleted
    automatically -- use ``helm uninstall`` on the target VM for
    full cleanup.
    """
    svc = get_app_install_service()
    result = await asyncio.to_thread(svc.uninstall_app, vm_name, app_id)
    return result.model_dump()
