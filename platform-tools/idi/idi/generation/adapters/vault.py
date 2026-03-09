"""HashiCorp Vault API adapter.

Handles Vault's dynamic mount points, multiple backends, and variable
response structures that differ by backend type:

- KV v1: ``{"data": {...}}``
- KV v2: ``{"data": {"data": {...}, "metadata": {...}}}``
- Auth:  ``{"auth": {"client_token": "...", "policies": [...]}}``
- Sys:   ``{"data": {...}}``
- Database / PKI / SSH / Transit: ``{"data": {...}}``

The default REST adapter cannot navigate these nested wrappers, so this
adapter provides:

1. **Backend detection** from API path patterns.
2. **Response schema unwrapping** that navigates to the real payload.
3. **Mount-point parameterization** for ``/auth/{mount}/...`` paths.
4. **FK detection** following the same interface as other adapters.
5. **Output extraction** with backend-aware fact URIs.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from idi.generation.fact_model import FactRef, ProducedFact, normalize_field, strip_id_suffix


# ---------------------------------------------------------------------------
# Backend constants
# ---------------------------------------------------------------------------

# Maps backend type -> path through the JSON response to reach the real data.
BACKEND_RESPONSE_PATHS: Dict[str, List[str]] = {
    "kv_v1":     ["data"],
    "kv_v2":     ["data", "data"],
    "auth":      ["auth"],
    "sys":       ["data"],
    "database":  ["data"],
    "pki":       ["data"],
    "ssh":       ["data"],
    "transit":   ["data"],
}

# Auth-specific output facts that are always present on auth responses.
AUTH_OUTPUT_FACTS: Dict[str, str] = {
    "client_token":   "client_token",
    "accessor":       "accessor",
    "policies":       "policies",
    "lease_duration": "lease_duration",
    "renewable":      "renewable",
}

# Well-known Vault auth method mount names.
KNOWN_AUTH_TYPES: List[str] = [
    "ldap", "oidc", "aws", "azure", "gcp",
    "kubernetes", "jwt", "github", "okta",
    "approle", "cert", "token", "userpass",
    "radius", "kerberos",
]

# Fields to exclude from FK detection (audit / metadata).
EXCLUDED_FIELDS = frozenset({
    "request_id",
    "lease_id",
    "lease_duration",
    "renewable",
    "wrap_info",
    "warnings",
    "auth",
    "data",
})


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class VaultAdapter:
    """Adapter for HashiCorp Vault API specs.

    Follows the same constructor signature as all other adapters::

        adapter = VaultAdapter(service="vault", known_resources=set())

    and exposes ``extract_field_refs``, ``extract_outputs``,
    ``extract_response_schema``, plus Vault-specific helpers.
    """

    def __init__(self, service: str, known_resources: Optional[Set[str]] = None):
        self.service = service.lower()
        self.known_resources = known_resources or set()

    # ------------------------------------------------------------------
    # Backend detection
    # ------------------------------------------------------------------

    def detect_backend_type(self, path: str) -> str:
        """Detect Vault backend type from an API path.

        Args:
            path: API path, e.g. ``/secret/data/{path}``, ``/auth/ldap/config``

        Returns:
            One of: ``kv_v2``, ``kv_v1``, ``auth``, ``sys``, ``database``,
            ``pki``, ``ssh``, ``transit``, or ``unknown``.
        """
        path_lower = path.lower().rstrip("/")

        # Auth paths
        if path_lower.startswith("/auth/") or path_lower == "/auth":
            return "auth"

        # KV v2 uses /secret/data/ or /{mount}/data/
        if "/data/" in path_lower and (
            path_lower.startswith("/secret") or "/secret" in path_lower
        ):
            return "kv_v2"

        # KV v2 metadata / delete / destroy / undelete paths
        for kv2_segment in ("/metadata/", "/destroy/", "/undelete/"):
            if kv2_segment in path_lower and (
                path_lower.startswith("/secret") or "/secret" in path_lower
            ):
                return "kv_v2"

        # KV v1 (plain /secret/{path} without /data/)
        if path_lower.startswith("/secret/") or path_lower == "/secret":
            return "kv_v1"

        # System backend
        if path_lower.startswith("/sys/") or path_lower == "/sys":
            return "sys"

        # Specific secret engine backends
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

    # ------------------------------------------------------------------
    # Mount-point parameterization
    # ------------------------------------------------------------------

    def parameterize_mount_point(self, path: str) -> Tuple[str, Optional[str]]:
        """Convert a concrete auth mount path to a parameterized form.

        Example::

            /auth/ldap/config  ->  (/auth/{mount}/config, "ldap")
            /auth/oidc/role/reader  ->  (/auth/{mount}/role/reader, "oidc")

        Args:
            path: Original API path.

        Returns:
            ``(parameterized_path, mount_type)`` where *mount_type* is the
            concrete mount name if recognised, or ``None`` if the path
            cannot be parameterized.
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

    # ------------------------------------------------------------------
    # Response schema extraction (the core value of this adapter)
    # ------------------------------------------------------------------

    def extract_response_schema(
        self,
        operation: Dict[str, Any],
        method: str,
        path: str,
        *,
        spec: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Extract the *real* response schema after unwrapping Vault's envelope.

        Vault responses are always wrapped.  This method:

        1. Determines the backend from *path*.
        2. Loads the success response schema from the OpenAPI operation.
        3. Navigates through the backend-specific wrapper keys
           (e.g. ``data -> data`` for KV v2).
        4. Returns the inner schema so callers see only actual fields.

        Args:
            operation: OpenAPI operation dict (contains ``responses``).
            method: HTTP method (``GET``, ``POST``, ...).
            path: API path used for backend detection.
            spec: Full OpenAPI spec dict, needed only for ``$ref`` resolution.
                  If ``None``, ``$ref`` values are returned as-is.

        Returns:
            Inner schema dict, or ``None`` if no success response found.
        """
        backend = self.detect_backend_type(path)

        # --- locate success response schema ---
        responses = operation.get("responses", {})
        success_response = None
        for code in ("200", "201", "204", "202"):
            if code in responses:
                success_response = responses[code]
                break

        if not success_response:
            return None

        # OpenAPI 3.x: content -> application/json -> schema
        content = success_response.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})

        # Swagger 2.0 fallback: schema directly on response
        if not schema and "schema" in success_response:
            schema = success_response["schema"]

        if not schema:
            return None

        # --- navigate into backend-specific wrapper ---
        response_path = BACKEND_RESPONSE_PATHS.get(backend, ["data"])

        current = schema
        for key in response_path:
            props = current.get("properties", {})
            if key in props:
                current = props[key]
            else:
                # Wrapper key not found in the schema -- return the outer
                # schema so the generator still has something to work with.
                return schema

        return current

    # ------------------------------------------------------------------
    # KV backend helpers (Task 2.2)
    # ------------------------------------------------------------------

    def handle_kv_backend(
        self,
        path: str,
        operation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Annotate an operation dict with KV version metadata.

        KV v1: ``/secret/{path}``
            Response: ``{"data": {"foo": "bar"}}``

        KV v2: ``/secret/data/{path}``
            Response: ``{"data": {"data": {"foo": "bar"}, "metadata": {...}}}``

        Returns the *operation* dict with private metadata keys added:

        - ``_vault_kv_version``: ``"v1"`` or ``"v2"``
        - ``_vault_response_path``: list of keys to traverse
        """
        if "/data/" in path:
            operation["_vault_kv_version"] = "v2"
            operation["_vault_response_path"] = ["data", "data"]
        else:
            operation["_vault_kv_version"] = "v1"
            operation["_vault_response_path"] = ["data"]

        return operation

    # ------------------------------------------------------------------
    # Auth backend helpers (Task 2.3)
    # ------------------------------------------------------------------

    def handle_auth_backend(
        self,
        path: str,
        operation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Annotate an operation dict with auth-backend metadata.

        Auth login responses look like::

            {"auth": {"client_token": "...", "policies": [...], ...}}

        Returns the *operation* dict with private metadata keys added:

        - ``_vault_backend_type``: ``"auth"``
        - ``_vault_response_path``: ``["auth"]``
        - ``_vault_auth_outputs``: dict mapping fact URIs to field names
        """
        operation["_vault_backend_type"] = "auth"
        operation["_vault_response_path"] = ["auth"]

        # Determine the auth mount type for fact URI construction
        _, mount_type = self.parameterize_mount_point(path)
        resource_suffix = mount_type or "token"

        auth_outputs: Dict[str, str] = {}
        for field, response_field in AUTH_OUTPUT_FACTS.items():
            fact_key = f"facts://{self.service}/auth-{resource_suffix}#{field}"
            auth_outputs[fact_key] = response_field

        operation["_vault_auth_outputs"] = auth_outputs

        return operation

    # ------------------------------------------------------------------
    # FK / field-ref detection (same interface as other adapters)
    # ------------------------------------------------------------------

    def extract_field_refs(
        self,
        schema: Optional[Dict[str, Any]],
        source_resource: str,
    ) -> List[Dict[str, Any]]:
        """Extract FK references from a Vault request body schema.

        Vault schemas tend to have fewer cross-resource FKs than REST APIs,
        but mount-path references and role names act as dependencies.

        Args:
            schema: OpenAPI schema dict (request body).
            source_resource: Resource name making the request.

        Returns:
            List of ref dicts: ``{field, target_resource, type, source}``.
        """
        if not schema or not isinstance(schema, dict):
            return []

        refs: List[Dict[str, Any]] = []
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return refs

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            if prop_name.lower() in EXCLUDED_FIELDS:
                continue

            # Mount-path reference (e.g. "auth_mount" pointing to an enabled auth mount)
            if prop_name.lower() in ("mount_point", "mount", "auth_mount", "secret_mount"):
                refs.append({
                    "field": prop_name,
                    "target_resource": "sys-auth",
                    "type": "string",
                    "source": "vault_mount",
                })
                continue

            # Role reference
            if prop_name.lower().endswith("_role") or prop_name.lower() == "role_name":
                refs.append({
                    "field": prop_name,
                    "target_resource": "auth-role",
                    "type": "string",
                    "source": "vault_role",
                })
                continue

            # Policy reference
            if prop_name.lower() in ("policies", "token_policies", "identity_policies"):
                refs.append({
                    "field": prop_name,
                    "target_resource": "sys-policy",
                    "type": "array",
                    "source": "vault_policy",
                })
                continue

            # $ref handling
            if "$ref" in prop_schema:
                refs.append({
                    "field": prop_name,
                    "ref": prop_schema["$ref"],
                    "type": prop_schema.get("type", "object"),
                    "source": "$ref",
                })

        return refs

    # ------------------------------------------------------------------
    # Output extraction
    # ------------------------------------------------------------------

    def extract_outputs(
        self,
        response_schema: Optional[Dict[str, Any]],
        resource: str,
        operation: str,
    ) -> List[ProducedFact]:
        """Extract output facts from an (already unwrapped) response schema.

        Args:
            response_schema: The inner schema (after Vault envelope removed).
            resource: Resource name.
            operation: Operation type (create, retrieve, ...).

        Returns:
            List of ``ProducedFact`` instances.
        """
        if not response_schema or not isinstance(response_schema, dict):
            return []

        outputs: List[ProducedFact] = []
        properties = response_schema.get("properties", {})
        if not isinstance(properties, dict):
            return outputs

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue
            if prop_name.lower() in EXCLUDED_FIELDS:
                continue

            ref = FactRef(
                service=self.service,
                resource=resource,
                field=prop_name,
            )
            skill_path = f"{self.service}/{resource}/{operation}"
            outputs.append(ProducedFact(
                ref=ref,
                skill_path=skill_path,
                response_field=prop_name,
                operation=operation,
            ))

        return outputs

    # ------------------------------------------------------------------
    # Mount dependency extraction
    # ------------------------------------------------------------------

    def extract_mount_dependencies(
        self,
        path: str,
        operation: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Extract dependencies on mount points from a path.

        For ``/auth/{mount}/role/{role}``, the operation depends on the
        auth backend being enabled first.

        Args:
            path: API path.
            operation: OpenAPI operation dict (unused but kept for interface consistency).

        Returns:
            List of dependency dicts (same shape as ``depends_on`` entries).
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

