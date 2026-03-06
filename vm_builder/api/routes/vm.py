"""VM management API routes.

All domain errors are raised by the service layer and caught by the
centralized VmBuilderError handler in app.py.  Routes are thin
pass-throughs with no try/except blocks.
"""

import asyncio
from typing import Optional
from fastapi import APIRouter, Body, Query
from vm_builder.api.deps import get_vm_service, get_registry_service
from vm_builder.core.models import (
    VmCreateRequest,
    VmUpdateRequest,
    AppInstallRequest,
    AppConfigureRequest,
    WorkerCreateRequest,
    IngressValidateRequest,
)
from vm_builder import bws
from vm_builder.core.errors import VmNotFoundError

router = APIRouter(prefix="/api/v1", tags=["vm"])


@router.get("/vms")
async def list_vms(client: Optional[str] = Query(None)):
    svc = get_vm_service()
    vms = await asyncio.to_thread(svc.list_vms, client)
    return [v.model_dump() for v in vms]


@router.get("/vms/{vm_name}")
async def get_vm(vm_name: str):
    svc = get_vm_service()
    inv = await asyncio.to_thread(svc.get_vm, vm_name)
    return inv


@router.post("/vms")
async def create_vm(body: VmCreateRequest):
    svc = get_vm_service()
    registry_data = None
    try:
        reg_svc = get_registry_service()
        registry_data = await asyncio.to_thread(reg_svc._load)
    except Exception:
        pass
    result = await asyncio.to_thread(svc.create_vm, body, registry_data)
    return result.model_dump()


@router.delete("/vms/{vm_name}")
async def delete_vm(vm_name: str):
    svc = get_vm_service()
    await asyncio.to_thread(svc.delete_vm, vm_name)
    return {"deleted": vm_name}


@router.put("/vms/{vm_name}")
async def update_vm(vm_name: str, body: VmUpdateRequest):
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.update_vm, vm_name, body)
    return result.model_dump()


@router.post("/vms/{vm_name}/regenerate-keypair")
async def regenerate_keypair(vm_name: str):
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.regenerate_vm_keypair, vm_name)
    return result


@router.post("/vms/{vm_name}/deploy")
async def deploy_vm(vm_name: str, hypervisor: Optional[str] = Query(None)):
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.deploy_vm, vm_name, hypervisor)
    return result.model_dump()


@router.post("/vms/{vm_name}/destroy")
async def destroy_vm(vm_name: str, hypervisor: Optional[str] = Query(None)):
    """Trigger full VM teardown (DESTRUCTIVE -- irreversible).

    This triggers the destroy-vm.yml GitHub Actions workflow which will:
    1. Run terragrunt destroy on the hypervisor
    2. Defensive libvirt cleanup (virsh destroy/undefine)
    3. Remove the Tailscale device
    4. De-register the GitHub Actions runner

    Returns the same shape as phase triggers (PhaseRunResult).
    """
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.destroy_vm, vm_name, hypervisor)
    return result.model_dump()


@router.post("/vms/{vm_name}/phase/install-apps")
async def trigger_install_apps(vm_name: str):
    """Trigger Phase 3 -- install all selected apps on the VM.

    Dispatches the phase3-dynamic.yml workflow which reads selected_apps
    from BWS inventory and installs them via the matrix strategy.
    """
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.trigger_phase3, vm_name)
    return result.model_dump()


@router.post("/vms/{vm_name}/phase/configure-apps")
async def trigger_configure_apps(vm_name: str):
    """Trigger Phase 4 -- configure all installed apps on the VM.

    Dispatches the phase4-dynamic.yml workflow which reads installed apps
    from BWS inventory and runs config playbooks filtered by requires_apps.
    """
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.trigger_phase4, vm_name)
    return result.model_dump()


@router.post("/vms/{vm_name}/phase/ingress-sso")
async def trigger_ingress_sso(vm_name: str):
    """Trigger Phase 5 -- deploy ingress controller and SSO.

    Dispatches the phase5-deploy-ingress-sso.yml workflow which sets up
    Traefik, Authentik, IngressRoutes, and OAuth apps.
    """
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.trigger_phase5, vm_name)
    return result.model_dump()


@router.post("/vms/{vm_name}/apps/{app_id}/install")
async def install_app(vm_name: str, app_id: str, skip_deps: bool = Query(False)):
    """Install a single app on an existing VM.

    Triggers the install-app.yml GitHub Actions workflow targeting
    the VM's self-hosted runner (label: vm-{vm_name}).

    Returns 409 if dependencies are not satisfied (unless skip_deps=true).
    Returns 404 if the VM does not exist.
    """
    vm_svc = get_vm_service()
    reg_svc = get_registry_service()

    # get_vm raises VmNotFoundError if VM doesn't exist
    inv = await asyncio.to_thread(vm_svc.get_vm, vm_name)
    selected_apps = inv.get("apps", {}).get("selected_apps", [])

    request = AppInstallRequest(
        vm_name=vm_name,
        app_id=app_id,
        skip_dependency_check=skip_deps,
    )

    # install_app raises DependencyError if deps are missing
    result = await asyncio.to_thread(
        vm_svc.install_app, request, selected_apps, reg_svc
    )
    return result.model_dump()


@router.post("/vms/{vm_name}/apps/{app_id}/configure")
async def configure_app(
    vm_name: str, app_id: str, body: dict = Body(default={})
):
    """Configure a single app on an existing VM.

    Triggers the configure-app.yml GitHub Actions workflow targeting
    the VM's self-hosted runner. Config values are passed as JSON.

    Returns 409 if the app is not installed on the VM.
    Returns 404 if the VM does not exist.
    """
    vm_svc = get_vm_service()

    request = AppConfigureRequest(
        vm_name=vm_name,
        app_id=app_id,
        config=body,
    )

    # configure_app raises DependencyError if app not installed,
    # VmNotFoundError if VM not found
    result = await asyncio.to_thread(vm_svc.configure_app, request)
    return result.model_dump()


@router.post("/vms/{master_name}/workers")
async def create_worker(master_name: str, body: WorkerCreateRequest):
    """Create a K3s worker node linked to a master."""
    svc = get_vm_service()
    result = await asyncio.to_thread(
        svc.create_worker,
        master_name=master_name,
        size=body.size,
        apps=body.apps,
    )
    return result.model_dump()


@router.get("/vms/{master_name}/workers")
async def list_workers(master_name: str):
    """List K3s worker nodes belonging to a master."""
    svc = get_vm_service()
    all_vms = await asyncio.to_thread(svc.list_vms)
    workers = [
        v.model_dump() for v in all_vms
        if v.master_name == master_name
    ]
    return workers


@router.post("/vms/{master_name}/persist-token")
async def persist_cluster_token(master_name: str):
    """Persist K3s join token from deploy workflow to master inventory."""
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.persist_cluster_token, master_name)
    return result


@router.post("/ingress/validate")
async def validate_ingress(body: IngressValidateRequest):
    """Validate ingress configuration (mode + domain).

    Returns a validation result indicating whether the given ingress
    mode and domain combination is valid for VM provisioning.
    """
    svc = get_vm_service()
    result = await asyncio.to_thread(svc.validate_ingress, body.mode, body.domain)
    return result.model_dump()


@router.get("/ingress/tailnet")
async def get_tailnet_name():
    """Return the Tailscale tailnet name from BWS.

    Used by the frontend to build Tailscale MagicDNS URL previews
    (e.g. https://{app}.{vm_hostname}.{tailnet}).

    Raises BwsSecretError (caught by centralized handler) if not configured.
    """
    try:
        tailnet = await asyncio.to_thread(
            bws.get_secret,
            "inventory/shared/secrets/tailscale/tailnet",
        )
    except Exception:
        raise VmNotFoundError(
            "Tailscale tailnet not configured. Set it on the Init Secrets page.",
            context={"secret_path": "inventory/shared/secrets/tailscale/tailnet"},
            hint="Configure the tailnet secret on the Init Secrets page",
        )
    return {"tailnet": tailnet}
