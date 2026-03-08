"""Schema and validation API routes."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from vm_builder.schema import SIZE_PRESETS, GCP_SIZE_PRESETS, RESOURCE_DEFAULTS, K3S_OVERHEAD_CPU_MILLICORES, K3S_OVERHEAD_MEMORY_MB, parse_vm_name

router = APIRouter(prefix="/api/v1/schema", tags=["schema"])

# Map platform identifiers to their size preset dictionaries
PLATFORM_SIZE_MAP = {
    "libvirt": SIZE_PRESETS,
    "gcp": GCP_SIZE_PRESETS,
}


class ValidateNameRequest(BaseModel):
    vm_name: str


@router.get("/sizes")
async def get_sizes(platform: str = Query(default="libvirt")):
    """Return size presets for the requested platform.

    Args:
        platform: Target platform identifier (libvirt, gcp).
    """
    presets = PLATFORM_SIZE_MAP.get(platform)
    if presets is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown platform: {platform}. Supported: {', '.join(sorted(PLATFORM_SIZE_MAP))}",
        )
    return presets


@router.get("/platforms")
async def get_platforms():
    return {
        "platforms": [
            {"id": "libvirt", "name": "QEMU/KVM via libvirt", "os": "Linux"},
            {"id": "gcp", "name": "Google Cloud Platform", "os": "Cloud"},
            {"id": "vsphere", "name": "VMware vSphere/ESXi", "os": "Any"},
        ]
    }


@router.post("/validate-name")
async def validate_name(body: ValidateNameRequest):
    is_valid, components, errors = parse_vm_name(body.vm_name)
    return {
        "valid": is_valid,
        "components": components if is_valid else {},
        "errors": errors,
    }


@router.get("/resource-defaults")
async def get_resource_defaults():
    """Get category-based resource defaults and k3s overhead.

    Returns a dict where each key is a category name mapping to
    resource requirements (min and recommended CPU/memory).

    Also includes a ``k3s_overhead`` key with the system reservation
    that should be subtracted from available hardware before tallying apps.

    Tallying formula (performed client-side):
        available_cpu = (vcpu * 1000) - k3s_overhead.cpu_millicores
        available_mem = memory_mb - k3s_overhead.memory_mb
        total_cpu = SUM(app.resources.min_cpu_millicores)
        total_mem = SUM(app.resources.min_memory_mb)
        usage_pct = total / available * 100
    """
    return {
        **RESOURCE_DEFAULTS,
        "k3s_overhead": {
            "cpu_millicores": K3S_OVERHEAD_CPU_MILLICORES,
            "memory_mb": K3S_OVERHEAD_MEMORY_MB,
        },
    }
