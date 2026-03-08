"""Top-level health orchestration for HealthService."""

from __future__ import annotations

from typing import Optional

from vm_builder.core.models import VmHealthStatus
from vm_builder.core.vm_service import VmService


def get_vm_health(
    self,
    client_filter: Optional[str] = None,
) -> list[VmHealthStatus]:
    """List inventory VMs and enrich each with Tailscale online/offline status."""
    vm_service = VmService()
    vms = vm_service.list_vms(client_filter=client_filter)
    vm_names = [vm.name for vm in vms]
    if not vm_names:
        return []

    devices = self._get_tailscale_devices()
    results = self._match_devices_to_vms(devices, vm_names)
    return sorted(results, key=lambda item: item.vm_name)
