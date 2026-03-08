"""Hypervisor service -- bootstrap script generation. Pure logic, no Click."""

from __future__ import annotations

import httpx
import time

from vm_builder import bws
from vm_builder.core.audit import AuditLogger
from vm_builder.core.errors import BwsSecretError, HypervisorNotFoundError, WorkflowTriggerError
from vm_builder.core.hypervisor_service_parts import check_prerequisites as check_prerequisites_part
from vm_builder.core.hypervisor_service_parts import constants as constants_part
from vm_builder.core.hypervisor_service_parts import create_github_runner_token as create_github_runner_token_part
from vm_builder.core.hypervisor_service_parts import create_hypervisor_inventory as create_hypervisor_inventory_part
from vm_builder.core.hypervisor_service_parts import create_tailscale_auth_key as create_tailscale_auth_key_part
from vm_builder.core.hypervisor_service_parts import generate_bootstrap_script as generate_bootstrap_script_part
from vm_builder.core.hypervisor_service_parts import get_hypervisor as get_hypervisor_part
from vm_builder.core.hypervisor_service_parts import get_tailscale_access_token as get_tailscale_access_token_part
from vm_builder.core.hypervisor_service_parts import list_hypervisors as list_hypervisors_part
from vm_builder.core.hypervisor_service_parts import trigger_phase0 as trigger_phase0_part
from vm_builder.core.hypervisor_service_parts import write_bootstrap_script as write_bootstrap_script_part
from vm_builder.core.models import (
    BootstrapScriptResult,
    HypervisorConfig,
    HypervisorSummary,
    PrereqResult,
)

TAILSCALE_API = constants_part.TAILSCALE_API
GITHUB_API = constants_part.GITHUB_API


class _ModuleProxy:
    """Proxy module attributes to current globals for patch-friendly tests."""

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def __getattr__(self, attr: str):
        return getattr(globals()[self._target_name], attr)


def _wire(module, **deps: str) -> None:
    for attr, target_name in deps.items():
        setattr(module, attr, _ModuleProxy(target_name))


_wire(check_prerequisites_part, bws="bws")
_wire(list_hypervisors_part, bws="bws")
_wire(get_hypervisor_part, bws="bws")
_wire(get_tailscale_access_token_part, httpx="httpx", time="time")
_wire(create_tailscale_auth_key_part, httpx="httpx", time="time")
_wire(create_github_runner_token_part, httpx="httpx", time="time")
_wire(create_hypervisor_inventory_part, bws="bws")
_wire(generate_bootstrap_script_part, bws="bws")
_wire(trigger_phase0_part, bws="bws", httpx="httpx")


class HypervisorService:
    """Service for hypervisor bootstrap script generation."""

    def __init__(self, audit_logger: AuditLogger | None = None) -> None:
        self._audit = audit_logger

    check_prerequisites = check_prerequisites_part.check_prerequisites

    list_hypervisors = list_hypervisors_part.list_hypervisors
    get_hypervisor = get_hypervisor_part.get_hypervisor

    _get_tailscale_access_token = get_tailscale_access_token_part.get_tailscale_access_token
    _create_tailscale_auth_key = create_tailscale_auth_key_part.create_tailscale_auth_key
    _create_github_runner_token = create_github_runner_token_part.create_github_runner_token

    _create_hypervisor_inventory = create_hypervisor_inventory_part.create_hypervisor_inventory

    generate_bootstrap_script = generate_bootstrap_script_part.generate_bootstrap_script

    trigger_phase0 = trigger_phase0_part.trigger_phase0

    write_bootstrap_script = write_bootstrap_script_part.write_bootstrap_script


__all__ = [
    "BootstrapScriptResult",
    "BwsSecretError",
    "GITHUB_API",
    "HypervisorConfig",
    "HypervisorNotFoundError",
    "HypervisorService",
    "HypervisorSummary",
    "PrereqResult",
    "TAILSCALE_API",
    "WorkflowTriggerError",
]
