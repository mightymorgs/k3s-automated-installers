"""Hypervisor API routes."""

import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from vm_builder.api.deps import get_hypervisor_service
from vm_builder.core.models import HypervisorConfig, Phase0TriggerRequest, Phase0TriggerResult
from vm_builder import bws

router = APIRouter(prefix="/api/v1", tags=["hypervisor"])


@router.get("/hypervisors")
async def list_hypervisors():
    """List all hypervisors from BWS inventory."""
    svc = get_hypervisor_service()
    return await asyncio.to_thread(svc.list_hypervisors)


@router.get("/hypervisors/{hypervisor_name}")
async def get_hypervisor(hypervisor_name: str):
    """Get full hypervisor inventory."""
    svc = get_hypervisor_service()
    try:
        return await asyncio.to_thread(svc.get_hypervisor, hypervisor_name)
    except bws.BWSError as e:
        raise HTTPException(404, str(e))


@router.post("/hypervisor/bootstrap")
async def generate_bootstrap(config: HypervisorConfig):
    svc = get_hypervisor_service()
    prereq = await asyncio.to_thread(svc.check_prerequisites)
    if not prereq.ok:
        raise HTTPException(400, prereq.error)
    try:
        result = await asyncio.to_thread(svc.generate_bootstrap_script, config)
    except Exception as e:
        raise HTTPException(500, str(e))
    return PlainTextResponse(
        content=result.script_content,
        media_type="text/x-shellscript",
        headers={
            "Content-Disposition": f'attachment; filename="{result.hypervisor_full_name}-bootstrap.sh"',
            "X-Hypervisor-Name": result.hypervisor_full_name,
            "X-Inventory-Key": result.inventory_key or "",
        },
    )


@router.post("/hypervisor/phase0", response_model=Phase0TriggerResult)
async def trigger_phase0(request: Phase0TriggerRequest):
    """Trigger Phase 0 workflow to install QEMU/libvirt on the hypervisor.

    The PAT is fetched server-side from BWS — it never leaves the server.
    The workflow runs on GitHub-hosted runner and SSHes via Tailscale.
    """
    svc = get_hypervisor_service()
    prereq = await asyncio.to_thread(svc.check_prerequisites)
    if not prereq.ok:
        raise HTTPException(400, prereq.error)
    try:
        result = await asyncio.to_thread(
            svc.trigger_phase0,
            request.hypervisor_name,
            request.force_reinstall,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))
    return Phase0TriggerResult(**result)
