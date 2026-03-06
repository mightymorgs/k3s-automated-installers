"""VM lifecycle and inventory models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class VmCreateRequest(BaseModel):
    """Request payload for creating or updating a VM inventory entry."""

    vm_name: str
    size: str
    platform: str
    hypervisor: Optional[str] = None
    vcpu: Optional[int] = None
    memory_mb: Optional[int] = None
    disk_size_gb: Optional[int] = None
    data_disk_size_gb: Optional[int] = None
    enable_gpu_passthrough: Optional[bool] = None
    gpu_pci_address: Optional[str] = None
    network_mode: Optional[str] = None
    bridge: Optional[str] = None
    static_ip: Optional[str] = None
    gateway: Optional[str] = None
    dns: Optional[list[str]] = None
    libvirt_uri: Optional[str] = None
    base_image_path: Optional[str] = None
    ssh_authorized_keys: Optional[list[str]] = None
    iac_version: Optional[str] = None
    apps: Optional[list[str]] = None
    app_configs: Optional[dict[str, dict]] = None
    ingress_mode: Optional[str] = None
    ingress_domain: Optional[str] = None
    sso_overrides: Optional[dict[str, bool]] = None
    ingress_app_overrides: Optional[dict[str, str]] = None
    storage_location: Optional[str] = None
    storage_mounts: Optional[list[dict]] = None
    storage_app_paths: Optional[dict[str, dict]] = None
    gcp: Optional[dict] = None


class WorkerCreateRequest(BaseModel):
    """Request payload for creating a K3s worker node."""

    size: str
    apps: Optional[list[str]] = None


class VmCreateResult(BaseModel):
    """Outcome of creating/updating a VM inventory entry."""

    inventory_key: str
    vm_name: str
    client: str
    platform: str
    size: str
    k3s_role: str
    apps_count: int
    ingress_mode: str = "nodeport"
    created: bool


class VmSummary(BaseModel):
    """Lightweight summary of a VM for list/table views."""

    name: str
    client: str
    platform: str
    state: str
    apps_count: int
    phase: str
    hypervisor: Optional[str] = None
    k3s_role: str = "none"
    master_name: Optional[str] = None
    worker_count: int = 0


class VmDeployResult(BaseModel):
    """Outcome of triggering a VM deploy workflow."""

    workflow_triggered: bool
    hypervisor_key: str
    run_url: Optional[str] = None
    run_status: Optional[str] = None
    error: Optional[str] = None
    phase5_triggered: bool = False
    ingress_mode: str = "nodeport"


class PhaseRunResult(BaseModel):
    """Outcome of triggering a phase workflow (Phase 3/4/5)."""

    phase: str
    workflow_triggered: bool
    run_url: Optional[str] = None
    run_status: Optional[str] = None
    error: Optional[str] = None


class VmHealthStatus(BaseModel):
    """Tailscale-based health status for a single VM."""

    vm_name: str
    tailscale_online: Optional[bool] = None
    tailscale_ip: Optional[str] = None
    last_seen: Optional[str] = None
    os: Optional[str] = None


class VmUpdateRequest(BaseModel):
    """Request payload for updating an existing VM inventory."""

    identity: Optional[dict] = None
    hardware: Optional[dict] = None
    network: Optional[dict] = None
    provider: Optional[dict] = None
    apps: Optional[dict] = None
    ssh: Optional[dict] = None
    tailscale: Optional[dict] = None


class VmUpdateResult(BaseModel):
    """Outcome of updating a VM inventory entry."""

    vm_name: str
    updated: bool
    changes: dict
    warnings: list[str]
