"""VM service -- inventory CRUD and deployment. Pure logic, no Click."""

from __future__ import annotations

import json
import subprocess
import time

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder import schema as schema_mod
from vm_builder.core.audit import AuditLogger
from vm_builder.core.errors import (
    BwsSecretError,
    DependencyError,
    HypervisorNotFoundError,
    ValidationError as VmValidationError,
    VmNotFoundError,
    WorkflowTriggerError,
)
from vm_builder.core.models import (
    AppConfigureRequest,
    AppConfigureResult,
    AppInstallRequest,
    AppInstallResult,
    IngressValidateResult,
    PrereqResult,
    VmCreateRequest,
    VmCreateResult,
    VmDeployResult,
    VmSummary,
    VmUpdateRequest,
    VmUpdateResult,
)
from vm_builder.core.workflow_names import WorkflowNames
from vm_builder.core.vm_service_parts import auto_detect_hypervisor as auto_detect_hypervisor_part
from vm_builder.core.vm_service_parts import build_inventory as build_inventory_part
from vm_builder.core.vm_service_parts import check_prerequisites as check_prerequisites_part
from vm_builder.core.vm_service_parts import configure_app as configure_app_part
from vm_builder.core.vm_service_parts import constants as constants_part
from vm_builder.core.vm_service_parts import create_vm as create_vm_part
from vm_builder.core.vm_service_parts import create_worker as create_worker_part
from vm_builder.core.vm_service_parts import delete_vm as delete_vm_part
from vm_builder.core.vm_service_parts import deploy_vm as deploy_vm_part
from vm_builder.core.vm_service_parts import destroy_vm as destroy_vm_part
from vm_builder.core.vm_service_parts import drain_k3s_node as drain_k3s_node_part
from vm_builder.core.vm_service_parts import fetch_latest_run as fetch_latest_run_part
from vm_builder.core.vm_service_parts import generate_ssh_keypair as generate_ssh_keypair_part
from vm_builder.core.vm_service_parts import get_vm as get_vm_part
from vm_builder.core.vm_service_parts import install_app as install_app_part
from vm_builder.core.vm_service_parts import list_vms as list_vms_part
from vm_builder.core.vm_service_parts import next_worker_index as next_worker_index_part
from vm_builder.core.vm_service_parts import persist_cluster_token as persist_cluster_token_part
from vm_builder.core.vm_service_parts import regenerate_vm_keypair as regenerate_vm_keypair_part
from vm_builder.core.vm_service_parts import update_vm as update_vm_part
from vm_builder.core.vm_service_parts import trigger_phase3 as trigger_phase3_part
from vm_builder.core.vm_service_parts import trigger_phase4 as trigger_phase4_part
from vm_builder.core.vm_service_parts import trigger_phase5 as trigger_phase5_part
from vm_builder.core.vm_service_parts import validate_ingress as validate_ingress_part

VALID_INGRESS_MODES = constants_part.VALID_INGRESS_MODES
DOMAIN_RE = constants_part.DOMAIN_RE
_NON_EDITABLE = constants_part.NON_EDITABLE
_READONLY_SECTIONS = constants_part.READONLY_SECTIONS


class _ModuleProxy:
    """Proxy module attributes to current globals for patch-friendly tests."""

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def __getattr__(self, attr: str):
        return getattr(globals()[self._target_name], attr)


def _wire(module, **deps: str) -> None:
    for attr, target_name in deps.items():
        setattr(module, attr, _ModuleProxy(target_name))


_wire(check_prerequisites_part, bws="bws", subprocess="subprocess")
_wire(generate_ssh_keypair_part, subprocess="subprocess")
_wire(build_inventory_part, bws="bws", schema_mod="schema_mod")
_wire(create_vm_part, bws="bws", schema_mod="schema_mod")
_wire(list_vms_part, bws="bws", schema_mod="schema_mod")
_wire(get_vm_part, bws="bws", schema_mod="schema_mod")
_wire(update_vm_part, bws="bws", schema_mod="schema_mod")
_wire(regenerate_vm_keypair_part, bws="bws")
_wire(delete_vm_part, bws="bws")
_wire(fetch_latest_run_part, subprocess="subprocess")
_wire(auto_detect_hypervisor_part, bws="bws")
_wire(deploy_vm_part, subprocess="subprocess", time="time")
_wire(persist_cluster_token_part, subprocess="subprocess", bws="bws")
_wire(next_worker_index_part, bws="bws", schema_mod="schema_mod")
_wire(create_worker_part, bws="bws", schema_mod="schema_mod")
_wire(drain_k3s_node_part, subprocess="subprocess")
_wire(destroy_vm_part, subprocess="subprocess", time="time")
_wire(install_app_part, subprocess="subprocess", time="time")
_wire(configure_app_part, subprocess="subprocess", time="time")
_wire(trigger_phase3_part, subprocess="subprocess", time="time", json="json")
_wire(trigger_phase4_part, subprocess="subprocess", time="time")
_wire(trigger_phase5_part, subprocess="subprocess", time="time")


class VmService:
    """Service for VM inventory management and deployment."""

    def __init__(self, audit_logger: AuditLogger | None = None) -> None:
        self._audit = audit_logger

    check_prerequisites = check_prerequisites_part.check_prerequisites
    _gh_repo_args = staticmethod(check_prerequisites_part.gh_repo_args)

    generate_ssh_keypair = generate_ssh_keypair_part.generate_ssh_keypair
    build_inventory = build_inventory_part.build_inventory
    create_vm = create_vm_part.create_vm
    list_vms = list_vms_part.list_vms
    get_vm = get_vm_part.get_vm
    update_vm = update_vm_part.update_vm
    regenerate_vm_keypair = regenerate_vm_keypair_part.regenerate_vm_keypair
    delete_vm = delete_vm_part.delete_vm

    deploy_vm = deploy_vm_part.deploy_vm
    persist_cluster_token = persist_cluster_token_part.persist_cluster_token
    _next_worker_index = next_worker_index_part.next_worker_index
    create_worker = create_worker_part.create_worker
    _drain_k3s_node = drain_k3s_node_part.drain_k3s_node
    destroy_vm = destroy_vm_part.destroy_vm

    install_app = install_app_part.install_app
    configure_app = configure_app_part.configure_app
    validate_ingress = validate_ingress_part.validate_ingress

    trigger_phase3 = trigger_phase3_part.trigger_phase3
    trigger_phase4 = trigger_phase4_part.trigger_phase4
    trigger_phase5 = trigger_phase5_part.trigger_phase5

    _fetch_latest_run = fetch_latest_run_part.fetch_latest_run
    _auto_detect_hypervisor = auto_detect_hypervisor_part.auto_detect_hypervisor


__all__ = [
    "AppConfigureRequest",
    "AppConfigureResult",
    "AppInstallRequest",
    "AppInstallResult",
    "BWSError",
    "BwsSecretError",
    "DependencyError",
    "DOMAIN_RE",
    "HypervisorNotFoundError",
    "IngressValidateResult",
    "PrereqResult",
    "VALID_INGRESS_MODES",
    "VmCreateRequest",
    "VmCreateResult",
    "VmDeployResult",
    "VmNotFoundError",
    "VmService",
    "VmSummary",
    "VmUpdateRequest",
    "VmUpdateResult",
    "VmValidationError",
    "WorkflowNames",
    "WorkflowTriggerError",
]
