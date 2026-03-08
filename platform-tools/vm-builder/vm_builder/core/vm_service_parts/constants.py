"""Constants for VM service operations."""

from __future__ import annotations

import re

VALID_INGRESS_MODES = {"nodeport", "tailscale", "cloudflare"}
DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$"
)

# Non-editable fields per section. These are silently preserved on update.
NON_EDITABLE = {
    "identity": {"hostname", "client", "vmtype", "subtype", "state", "purpose", "version"},
    "ssh": {"user", "keypair"},
    "tailscale": {"oauth_client_id_key", "oauth_client_secret_key", "tailnet_key"},
    "k3s": {"role", "cluster_token"},
}

# Sections that are entirely non-editable.
READONLY_SECTIONS = {"bootstrap", "_state", "schema_version"}
