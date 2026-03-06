"""Health service -- Tailscale-based VM health checks."""

from __future__ import annotations

import httpx

from vm_builder import bws
from vm_builder.core.health_service_parts import constants as constants_part
from vm_builder.core.health_service_parts import get_tailscale_access_token as get_tailscale_access_token_part
from vm_builder.core.health_service_parts import get_tailscale_devices as get_tailscale_devices_part
from vm_builder.core.health_service_parts import get_vm_health as get_vm_health_part
from vm_builder.core.health_service_parts import match_devices_to_vms as match_devices_to_vms_part
from vm_builder.core.models import VmHealthStatus
from vm_builder.core.vm_service import VmService

TAILSCALE_API = constants_part.TAILSCALE_API


class _ModuleProxy:
    """Proxy module attributes to current globals for patch-friendly tests."""

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def __getattr__(self, attr: str):
        return getattr(globals()[self._target_name], attr)

    def __call__(self, *args, **kwargs):
        return globals()[self._target_name](*args, **kwargs)


def _wire(module, **deps: str) -> None:
    for attr, target_name in deps.items():
        setattr(module, attr, _ModuleProxy(target_name))


_wire(get_tailscale_access_token_part, httpx="httpx")
_wire(get_tailscale_devices_part, bws="bws", httpx="httpx")
_wire(get_vm_health_part, VmService="VmService")


class HealthService:
    """Service for checking VM health via Tailscale device status."""

    _get_tailscale_access_token = (
        get_tailscale_access_token_part.get_tailscale_access_token
    )
    _get_tailscale_devices = get_tailscale_devices_part.get_tailscale_devices
    _match_devices_to_vms = match_devices_to_vms_part.match_devices_to_vms

    get_vm_health = get_vm_health_part.get_vm_health


__all__ = ["HealthService", "TAILSCALE_API", "VmHealthStatus", "VmService"]
