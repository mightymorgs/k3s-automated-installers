"""TypedDict definitions for VM inventory schemas."""

from __future__ import annotations

from typing import Literal, TypedDict


class InventorySchema(TypedDict, total=False):
    """VM inventory schema v3.1/v3.2/v3.3."""

    schema_version: Literal["v3.1", "v3.2", "v3.3"]
    identity: dict
    hardware: dict
    network: dict
    ssh: dict
    tailscale: dict
    k3s: dict
    provider: dict
    apps: dict
    ingress: dict
    storage: dict
    _config: dict
    _overrides: dict
    _state: dict
    bootstrap: dict
