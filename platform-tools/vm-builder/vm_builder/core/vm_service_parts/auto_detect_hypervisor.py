"""Hypervisor auto-detection for VM operations."""

from __future__ import annotations

import logging

from vm_builder import bws
from vm_builder.core.errors import HypervisorNotFoundError

logger = logging.getLogger(__name__)


def auto_detect_hypervisor(self, platform: str, client: str = "") -> str:
    """Auto-detect hypervisor by platform match.

    Hypervisor names follow the 4-segment format: hv-{name}-{platform}-{location}.
    Platform is at parts[2]. Client matching is not used (multi-tenant).
    """
    all_secrets = bws.list_secrets(filter_key="inventory/hypervisors/")
    hypervisors = [
        secret
        for secret in all_secrets
        if secret["key"].startswith("inventory/hypervisors/")
    ]

    logger.info(
        "auto_detect_hypervisor: platform=%s, found %d hypervisor keys: %s",
        platform,
        len(hypervisors),
        [h["key"] for h in hypervisors],
    )

    if not hypervisors:
        raise HypervisorNotFoundError(
            "No hypervisors found in BWS",
            context={"platform": platform},
        )

    matching = []
    for hypervisor in hypervisors:
        hv_name = hypervisor["key"].replace("inventory/hypervisors/", "")
        parts = hv_name.split("-")
        # New format: hv-{name}-{platform}-{location} → parts[2] = platform
        # Old format: {client}-hypervisor-standalone-{state}-{purpose}-{platform}-{location} → parts[5]
        if len(parts) >= 4 and parts[0] == "hv" and parts[2] == platform:
            matching.append(hypervisor["key"])
        elif len(parts) >= 6 and parts[1] == "hypervisor" and parts[5] == platform:
            matching.append(hypervisor["key"])

    if not matching:
        raise HypervisorNotFoundError(
            f"No hypervisors found for platform: {platform}",
            context={"platform": platform},
        )

    return matching[0]
