"""VM health check API routes -- Tailscale-based online/offline status."""

import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from vm_builder.api.deps import get_health_service
from vm_builder.bws import BWSError

router = APIRouter(prefix="/api/v1", tags=["vm-health"])


@router.get("/vms/health")
async def get_vm_health(client: Optional[str] = Query(None)):
    """Get Tailscale health status for all VMs.

    Returns a list of VmHealthStatus objects, one per VM in inventory.

    Status dot legend:
    - green (tailscale_online=true): VM is connected to Tailscale
    - red (tailscale_online=false): VM exists in Tailscale but is offline
    - gray (tailscale_online=null): VM not found in Tailscale network

    Query params:
        client: Optional client name to filter VMs.
    """
    svc = get_health_service()
    try:
        results = await asyncio.to_thread(svc.get_vm_health, client_filter=client)
    except (BWSError, RuntimeError, Exception) as e:
        raise HTTPException(500, f"Health check failed: {e}")
    return [r.model_dump() for r in results]
