"""HashiCorp Vault API adapter.

Handles Vault-specific conventions that cannot be replaced by generic detection:
- Backend type detection from API path patterns
- Mount-point parameterization for auth paths
- Mount dependency extraction (auth paths depend on sys-auth)

Envelope unwrapping, FK detection, and output extraction are now handled by
generic detectors (envelope_detector, field_extractor, response tree walk).
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

KNOWN_AUTH_TYPES: List[str] = [
    "ldap", "oidc", "aws", "azure", "gcp",
    "kubernetes", "jwt", "github", "okta",
    "approle", "cert", "token", "userpass",
    "radius", "kerberos",
]


class VaultAdapter:
    """Adapter for HashiCorp Vault API specs.

    Retains only Vault-unique logic: backend detection, mount parameterization,
    and mount dependency extraction.
    """

    def __init__(self, service: str, known_resources: Optional[Set[str]] = None):
        self.service = service.lower()
        self.known_resources = known_resources or set()

    def detect_backend_type(self, path: str) -> str:
        """Detect Vault backend type from an API path.

        Returns one of: kv_v2, kv_v1, auth, sys, database, pki, ssh,
        transit, or unknown.
        """
        path_lower = path.lower().rstrip("/")

        if path_lower.startswith("/auth/") or path_lower == "/auth":
            return "auth"

        if "/data/" in path_lower and (
            path_lower.startswith("/secret") or "/secret" in path_lower
        ):
            return "kv_v2"

        for kv2_segment in ("/metadata/", "/destroy/", "/undelete/"):
            if kv2_segment in path_lower and (
                path_lower.startswith("/secret") or "/secret" in path_lower
            ):
                return "kv_v2"

        if path_lower.startswith("/secret/") or path_lower == "/secret":
            return "kv_v1"

        if path_lower.startswith("/sys/") or path_lower == "/sys":
            return "sys"

        backend_prefixes = {
            "/database/": "database",
            "/pki/":      "pki",
            "/ssh/":      "ssh",
            "/transit/":  "transit",
        }
        for prefix, backend in backend_prefixes.items():
            if path_lower.startswith(prefix):
                return backend

        return "unknown"

    def parameterize_mount_point(self, path: str) -> Tuple[str, Optional[str]]:
        """Convert a concrete auth mount path to a parameterized form.

        Example: /auth/ldap/config -> (/auth/{mount}/config, 'ldap')
        """
        match = re.match(r"^(/auth/)([^/]+)/(.+)$", path, re.IGNORECASE)
        if not match:
            return path, None

        prefix = match.group(1)
        mount_name = match.group(2).lower()
        rest = match.group(3)

        if mount_name in KNOWN_AUTH_TYPES:
            return f"{prefix}{{mount}}/{rest}", mount_name

        return path, None

    def extract_mount_dependencies(
        self,
        path: str,
        operation: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Extract dependencies on mount points from a path.

        Auth paths depend on the auth backend being enabled via sys-auth.
        """
        dependencies: List[Dict[str, Any]] = []

        if "{mount}" in path or "/auth/" in path.lower():
            dependencies.append({
                "path": f"{self.service}/sys-auth/create",
                "field": "path",
                "source": "vault_mount",
                "fact_ref": f"facts://{self.service}/sys-auth#path",
            })

        return dependencies
