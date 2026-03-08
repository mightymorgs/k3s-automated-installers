"""Atomic VM command handlers."""

from vm_builder.commands.vm_cmd.apps import (
    configure_app,
    install_apps,
    list_apps,
    uninstall_app,
)
from vm_builder.commands.vm_cmd.create import create_vm_inventory
from vm_builder.commands.vm_cmd.delete import delete_vm_inventory
from vm_builder.commands.vm_cmd.deploy import deploy_vm
from vm_builder.commands.vm_cmd.destroy import destroy_vm
from vm_builder.commands.vm_cmd.health import show_vm_health
from vm_builder.commands.vm_cmd.list import list_vms
from vm_builder.commands.vm_cmd.phase import trigger_phase
from vm_builder.commands.vm_cmd.regenerate_keypair import regenerate_keypair
from vm_builder.commands.vm_cmd.show import show_vm
from vm_builder.commands.vm_cmd.update import update_vm
from vm_builder.commands.vm_cmd.workers import (
    create_worker,
    list_workers,
    persist_worker_token,
)

__all__ = [
    "configure_app",
    "create_vm_inventory",
    "create_worker",
    "delete_vm_inventory",
    "deploy_vm",
    "destroy_vm",
    "install_apps",
    "list_apps",
    "list_vms",
    "list_workers",
    "persist_worker_token",
    "regenerate_keypair",
    "show_vm",
    "show_vm_health",
    "trigger_phase",
    "uninstall_app",
    "update_vm",
]
