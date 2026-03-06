"""VM list operation."""

from __future__ import annotations

from typing import Optional

from vm_builder import bws
from vm_builder import schema as schema_mod
from vm_builder.core.models import VmSummary


def list_vms(self, client_filter: Optional[str] = None) -> list[VmSummary]:
    """List VMs from BWS with cluster grouping info."""
    all_secrets = bws.list_secrets(filter_key="inventory/")
    vm_secrets = [
        secret
        for secret in all_secrets
        if secret["key"].startswith("inventory/")
        and secret["key"].count("/") == 1
        and "-" in secret["key"].split("/")[-1]
    ]

    if client_filter:
        vm_secrets = [
            secret
            for secret in vm_secrets
            if secret["key"].split("/")[1].startswith(f"{client_filter}-")
        ]

    vms: list[VmSummary] = []
    worker_masters: dict[str, str] = {}

    for secret in vm_secrets:
        try:
            inventory = bws.get_secret_by_id(secret["id"])
            if isinstance(inventory, dict):
                inventory = schema_mod.migrate_inventory(inventory)
                vm_name = secret["key"].replace("inventory/", "")
                k3s = inventory.get("k3s", {})
                k3s_role = k3s.get("role", "none")
                master_name = k3s.get("master_name")

                if master_name:
                    worker_masters[vm_name] = master_name

                vms.append(
                    VmSummary(
                        name=vm_name,
                        client=inventory.get("identity", {}).get("client", "unknown"),
                        platform=inventory.get("identity", {}).get("platform", "unknown"),
                        state=inventory.get("identity", {}).get("state", "unknown"),
                        apps_count=len(inventory.get("apps", {}).get("selected_apps", [])),
                        phase=inventory.get("_state", {}).get("bootstrap", {}).get(
                            "phase_completed", "-"
                        ),
                        hypervisor=inventory.get("provider", {}).get("hypervisor"),
                        k3s_role=k3s_role,
                        master_name=master_name,
                    )
                )
        except Exception:
            pass

    worker_counts: dict[str, int] = {}
    for master in worker_masters.values():
        worker_counts[master] = worker_counts.get(master, 0) + 1

    for vm in vms:
        if vm.name in worker_counts:
            vm.worker_count = worker_counts[vm.name]

    return sorted(vms, key=lambda vm: vm.name)
