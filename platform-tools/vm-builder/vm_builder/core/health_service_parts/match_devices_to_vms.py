"""Device-to-VM matching for HealthService."""

from __future__ import annotations

from vm_builder.core.models import VmHealthStatus


def match_devices_to_vms(self, devices: list[dict], vm_names: list[str]) -> list[VmHealthStatus]:
    """Match Tailscale devices to inventory VM names by hostname."""
    device_map: dict[str, dict] = {}
    for device in devices:
        hostname = device.get("hostname", "")
        if hostname:
            device_map[hostname] = device

    results: list[VmHealthStatus] = []
    for vm_name in vm_names:
        device = device_map.get(vm_name)
        if device:
            addresses = device.get("addresses", [])
            results.append(
                VmHealthStatus(
                    vm_name=vm_name,
                    tailscale_online=device.get("connectedToControl", False),
                    tailscale_ip=addresses[0] if addresses else None,
                    last_seen=device.get("lastSeen"),
                    os=device.get("os"),
                )
            )
            continue

        results.append(
            VmHealthStatus(
                vm_name=vm_name,
                tailscale_online=None,
                tailscale_ip=None,
                last_seen=None,
                os=None,
            )
        )

    return results
