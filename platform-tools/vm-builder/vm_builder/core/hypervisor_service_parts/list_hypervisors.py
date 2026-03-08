"""Hypervisor list operation."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.core.models import HypervisorSummary


def list_hypervisors(self) -> list[HypervisorSummary]:
    """List all hypervisors from BWS inventory."""
    all_secrets = bws.list_secrets(filter_key="inventory/hypervisors/")
    hypervisors = []

    for secret in all_secrets:
        if not secret["key"].startswith("inventory/hypervisors/"):
            continue

        try:
            inventory = bws.get_secret_by_id(secret["id"])
            if isinstance(inventory, dict):
                identity = inventory.get("identity", {})
                bootstrap = inventory.get("bootstrap", {})
                hypervisors.append(
                    HypervisorSummary(
                        name=identity.get(
                            "full_name",
                            secret["key"].replace("inventory/hypervisors/", ""),
                        ),
                        platform=identity.get("platform", "unknown"),
                        location=identity.get("location", "unknown"),
                        phase0_completed=bootstrap.get(
                            "phase0_qemu_setup_completed", False
                        ),
                        ready_for_phase2=bootstrap.get("ready_for_phase2", False),
                    )
                )
        except Exception:
            pass

    return sorted(hypervisors, key=lambda hypervisor: hypervisor.name)
