"""Worker index helper for VM service."""

from __future__ import annotations

from vm_builder import bws
from vm_builder import schema as schema_mod


def next_worker_index(self, master_name: str) -> int:
    """Determine the next worker index for a master."""
    _, master_components, _ = schema_mod.parse_vm_name(master_name)
    purpose = master_components["purpose"]

    all_secrets = bws.list_secrets(filter_key="inventory/")
    worker_prefix = (
        f"inventory/{master_components['client']}-k3s-worker-"
        f"{master_components['state']}-{purpose}w"
    )
    existing = [
        secret
        for secret in all_secrets
        if secret["key"].startswith(worker_prefix)
    ]

    if not existing:
        return 1

    indices = []
    for secret in existing:
        worker_name = secret["key"].replace("inventory/", "")
        _, worker_components, _ = schema_mod.parse_vm_name(worker_name)
        worker_purpose = worker_components.get("purpose", "")
        suffix = worker_purpose.replace(purpose + "w", "")
        try:
            indices.append(int(suffix))
        except ValueError:
            continue

    return max(indices, default=0) + 1
