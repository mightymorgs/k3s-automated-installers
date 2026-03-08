"""Hypervisor-related models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, computed_field


class HypervisorConfig(BaseModel):
    """Configuration for a hypervisor host."""

    name: str         # unique identifier (auros15g, imac)
    platform: str     # libvirt, vsphere, proxmox
    location: str     # office, datacenter
    local_ip: str
    github_repo: str
    network_mode: str
    ssh_user: str = "morgs"
    vm_builder_api_url: Optional[str] = None

    @computed_field
    @property
    def full_name(self) -> str:
        """Build canonical 4-segment hypervisor name.

        Format: hv-{name}-{platform}-{location}
        Multi-tenant: no client/state baked into the name.
        Per-hypervisor Tailscale tag (tag:hv-{name}) scopes VM access.
        """
        return f"hv-{self.name}-{self.platform}-{self.location}"


class Phase0TriggerRequest(BaseModel):
    """Request payload for triggering Phase 0 workflow."""

    hypervisor_name: str
    force_reinstall: bool = False


class Phase0TriggerResult(BaseModel):
    """Result of triggering Phase 0 workflow."""

    triggered: bool
    repo: str
    workflow: str
    hypervisor_name: str
    inventory_key: str
    force_reinstall: bool = False


class BootstrapScriptResult(BaseModel):
    """Result of generating a hypervisor bootstrap script."""

    script_content: str
    hypervisor_full_name: str
    inventory_key: Optional[str] = None
    output_path: Optional[str] = None
    tailscale_device_cleaned: bool = False
    github_runner_cleaned: bool = False


class HypervisorSummary(BaseModel):
    """Lightweight summary of a hypervisor for list/table views."""

    name: str
    platform: str
    location: str
    phase0_completed: bool
    ready_for_phase2: bool
