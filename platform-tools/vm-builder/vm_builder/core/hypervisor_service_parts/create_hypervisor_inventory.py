"""Hypervisor inventory create/update operation."""

from __future__ import annotations

import logging
from datetime import datetime

from vm_builder import bws
from vm_builder.core.models import HypervisorConfig

logger = logging.getLogger(__name__)


def create_hypervisor_inventory(self, config: HypervisorConfig, runner_name: str) -> str:
    """Create or update the hypervisor inventory entry in BWS."""
    inventory_key = f"inventory/hypervisors/{config.full_name}"

    inventory = {
        "schema_version": "3.1",
        "identity": {
            "full_name": config.full_name,
            "name": config.name,
            "platform": config.platform,
            "location": config.location,
        },
        "hardware": {
            "local_ip": config.local_ip,
        },
        "network": {
            "mode": config.network_mode,
        },
        "ssh": {
            "user": config.ssh_user or "morgs",
        },
        "github": {
            "repo": config.github_repo,
            "runner_name": runner_name,
        },
        "bootstrap": {
            "inventory_created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "phase0_qemu_setup_completed": False,
            "ready_for_phase2": False,
        },
        "_state": {},
    }

    if bws.secret_exists(inventory_key):
        existing = bws.get_secret(inventory_key)
        if isinstance(existing, dict):
            preserved_state = existing.get("_state", {})
            existing.update(inventory)
            existing["_state"] = preserved_state
            inventory = existing

        secrets = bws.list_secrets(filter_key=inventory_key)
        matching = [secret for secret in secrets if secret["key"] == inventory_key]
        if matching:
            bws.edit_secret(matching[0]["id"], inventory)
            logger.info("Updated existing hypervisor inventory: %s", inventory_key)
    else:
        bws.create_secret(inventory_key, inventory)
        logger.info("Created hypervisor inventory: %s", inventory_key)

    return inventory_key
