"""Constants used by registry generation functions."""

from __future__ import annotations

PLATFORM_PREREQUISITES = {
    "k3s_server_installed": "k3s",
    "k3s_control_plane_ready": "k3s",
    "disks_attached": None,
    "longhorn_deployed": "longhorn",
    "longhorn_installed": "longhorn",
}

CAPABILITY_ALIASES = {
    "vault_server_deployed": "vault",
    "vault_unsealed": "vault",
    "vault_ready": "vault",
    "vault_initialized": "vault",
    "media_shared_storage_deployed": "media-shared",
    "eso_deployed": "external-secrets",
}
