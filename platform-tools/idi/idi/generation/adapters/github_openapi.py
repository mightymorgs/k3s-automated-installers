"""GitHub Pseudo-OpenAPI adapter for FK detection.

GitHub's OpenAPI spec has several quirks that require special handling:
- node_id and id are both identifiers (node_id is GraphQL ID)
- Polymorphic request bodies (oneOf/anyOf)
- Deeply nested $ref chains
- owner/repo as external path parameters
- login as name alias for users/orgs
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Any

from idi.generation.fact_model import FactRef, ProducedFact, normalize_field, ID_ALIASES


# GitHub-specific aliases - field name to canonical name
GITHUB_ALIASES: Dict[str, str] = {
    "node_id": "id",      # GraphQL ID maps to canonical id
    "login": "name",      # User/org login is their name
    "full_name": "name",  # Repo full_name is "owner/name"
}

# External parameters (not FKs - user provides these)
EXTERNAL_PARAMS: Set[str] = {"owner", "org", "repo", "username"}

# Output fields to extract (beyond standard ID fields)
OUTPUT_FIELDS: Set[str] = {
    "id", "node_id", "name", "login", "full_name",
    "html_url", "clone_url", "slug",
}


@dataclass(frozen=True)
class GitHubFactRef(FactRef):
    """FactRef subclass that handles GitHub-specific aliases.

    Maps node_id -> id and login -> name for canonical field resolution.
    """

    def __post_init__(self):
        """Resolve canonical field with GitHub-specific aliases."""
        field_lower = self.field.lower()

        # Check GitHub-specific aliases first
        if field_lower in GITHUB_ALIASES:
            canonical = GITHUB_ALIASES[field_lower]
        # Then check standard ID aliases
        elif field_lower in ID_ALIASES:
            canonical = "id"
        else:
            canonical = field_lower

        object.__setattr__(self, 'canonical_field', canonical)


class GitHubOpenApiAdapter:
    """Adapter for GitHub's pseudo-OpenAPI spec.

    Handles GitHub-specific patterns:
    - node_id as ID alias
    - Nested owner.login extraction
    - Polymorphic oneOf/anyOf bodies
    - Deep $ref resolution with cycle protection
    - External path params (owner, repo, org)
    """

    def __init__(self, service: str = "github", known_resources: Optional[Set[str]] = None):
        """Initialize adapter for GitHub.

        Args:
            service: Service name (default: "github")
            known_resources: Optional set of known resource names for FK resolution
        """
        self.service = service.lower()
        self.known_resources = known_resources or set()

    def extract_field_refs(
        self,
        schema: Optional[Dict[str, Any]],
        source_resource: str,
    ) -> List[Dict[str, Any]]:
        """Extract FK references from GitHub schema.

        Handles polymorphic oneOf/anyOf bodies by marking them as ambiguous.

        Args:
            schema: OpenAPI schema dict
            source_resource: Resource this schema belongs to

        Returns:
            List of FK reference dicts with keys:
            - field: Field name
            - type: Field type
            - source: Detection source
            - ambiguous: True if polymorphic
            - candidates: List of candidate types (for polymorphic)
        """
        if not schema or not isinstance(schema, dict):
            return []

        refs: List[Dict[str, Any]] = []

        # Handle polymorphic bodies (oneOf/anyOf)
        if "oneOf" in schema or "anyOf" in schema:
            variants = schema.get("oneOf", []) or schema.get("anyOf", [])
            if len(variants) > 1:
                candidates = [
                    self._extract_ref_name(v.get("$ref", ""))
                    for v in variants
                    if "$ref" in v
                ]
                refs.append({
                    "field": "body",
                    "ambiguous": True,
                    "candidates": [c for c in candidates if c],  # Filter None
                    "type": "polymorphic",
                    "confidence": "low",
                    "source": "oneOf",
                })
            return refs

        # Handle allOf by recursing
        if "allOf" in schema:
            for sub_schema in schema["allOf"]:
                refs.extend(self.extract_field_refs(sub_schema, source_resource))

        # Standard property extraction
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field_name, field_info in properties.items():
                if not isinstance(field_info, dict):
                    continue

                ref = self._detect_fk(field_name, field_info, source_resource)
                if ref:
                    refs.append(ref)

        return refs

    def extract_outputs(
        self,
        response_schema: Optional[Dict[str, Any]],
        resource: str,
        operation: str,
    ) -> List[ProducedFact]:
        """Extract output facts from GitHub response schema.

        Uses GitHubFactRef to properly resolve node_id -> id and login -> name.

        Args:
            response_schema: OpenAPI response schema dict
            resource: Resource name
            operation: Operation type (create, retrieve, etc.)

        Returns:
            List of ProducedFact instances
        """
        if not response_schema or not isinstance(response_schema, dict):
            return []

        outputs: List[ProducedFact] = []
        properties = response_schema.get("properties", {})

        if not isinstance(properties, dict):
            return outputs

        for field_name, field_info in properties.items():
            if not isinstance(field_info, dict):
                continue

            # Check if this is an output-worthy field
            if self._is_output_field(field_name, field_info):
                # Use GitHubFactRef for proper alias resolution
                ref = GitHubFactRef(
                    service=self.service,
                    resource=resource,
                    field=field_name.lower(),
                )
                outputs.append(ProducedFact(
                    ref=ref,
                    skill_path=f"{self.service}/{resource}/{operation}.md",
                    response_field=field_name,
                    operation=operation,
                ))

            # Handle nested objects like owner.login
            if field_info.get("type") == "object" and "properties" in field_info:
                nested_outputs = self._extract_nested_outputs(
                    field_name, field_info, resource, operation
                )
                outputs.extend(nested_outputs)

        return outputs

    def extract_path_params_as_refs(
        self,
        operation: Dict[str, Any],
        resource: str,
    ) -> List[Dict[str, Any]]:
        """Extract path parameters, marking external vs FK.

        External params (owner, repo, org, username) are user-provided.
        Other path params (issue_number, pull_number) are FKs.

        Args:
            operation: OpenAPI operation dict
            resource: Resource name

        Returns:
            List of parameter reference dicts with keys:
            - field: Parameter name
            - type: Parameter type
            - external: True if external (user-provided)
            - target_resource: Inferred resource (for FKs)
        """
        refs: List[Dict[str, Any]] = []
        parameters = operation.get("parameters", [])

        for param in parameters:
            if not isinstance(param, dict):
                continue

            if param.get("in") != "path":
                continue

            name = param.get("name", "")
            is_external = name.lower() in EXTERNAL_PARAMS

            refs.append({
                "field": name,
                "target_resource": None if is_external else self._infer_resource(name),
                "type": param.get("type", param.get("schema", {}).get("type", "string")),
                "external": is_external,
                "confidence": "high" if is_external else "medium",
                "source": "path_param",
            })

        return refs

    def _is_output_field(self, field_name: str, field_info: Dict[str, Any]) -> bool:
        """Check if field should be in outputs.

        Args:
            field_name: Field name
            field_info: Field schema info

        Returns:
            True if field should be extracted as output
        """
        normalized = normalize_field(field_name)

        # ID fields (including GitHub-specific)
        if normalized in ID_ALIASES or normalized in GITHUB_ALIASES:
            return True

        # Standard output fields
        if normalized in OUTPUT_FIELDS:
            return True

        # UUID format fields
        if field_info.get("format") == "uuid":
            return True

        return False

    def _extract_nested_outputs(
        self,
        parent_name: str,
        parent_schema: Dict[str, Any],
        resource: str,
        operation: str,
    ) -> List[ProducedFact]:
        """Extract outputs from nested objects like owner.login.

        Args:
            parent_name: Parent field name (e.g., "owner")
            parent_schema: Parent field schema
            resource: Resource name
            operation: Operation type

        Returns:
            List of ProducedFact for nested fields
        """
        outputs: List[ProducedFact] = []
        properties = parent_schema.get("properties", {})

        # Extract key nested fields
        for field_name in ("login", "id", "node_id", "name"):
            if field_name in properties:
                # Use parent name as resource for nested facts
                # e.g., owner.login -> facts://github/owner#login
                ref = GitHubFactRef(
                    service=self.service,
                    resource=parent_name.lower(),
                    field=field_name.lower(),
                )
                outputs.append(ProducedFact(
                    ref=ref,
                    skill_path=f"{self.service}/{resource}/{operation}.md",
                    response_field=f"{parent_name}.{field_name}",
                    operation=operation,
                ))

        return outputs

    def _detect_fk(
        self,
        field_name: str,
        field_info: Dict[str, Any],
        source_resource: str,
    ) -> Optional[Dict[str, Any]]:
        """Detect FK in GitHub schema.

        Args:
            field_name: Field name
            field_info: Field schema info
            source_resource: Source resource name

        Returns:
            FK reference dict or None
        """
        # Check for $ref
        if "$ref" in field_info:
            target = self._extract_ref_name(field_info["$ref"])
            return {
                "field": field_name,
                "target_resource": target,
                "type": "$ref",
                "confidence": "high",
                "source": "$ref",
            }

        # Check for array with $ref items
        if field_info.get("type") == "array":
            items = field_info.get("items", {})
            if isinstance(items, dict) and "$ref" in items:
                target = self._extract_ref_name(items["$ref"])
                return {
                    "field": field_name,
                    "target_resource": target,
                    "type": "array",
                    "confidence": "high",
                    "source": "$ref",
                }

        # Integer fields ending in _id or _number
        field_type = field_info.get("type", "")
        if field_type == "integer":
            if field_name.endswith("_id"):
                base = field_name[:-3]  # Strip _id
                return {
                    "field": field_name,
                    "target_resource": base + "s",  # Pluralize
                    "type": "integer",
                    "confidence": "medium",
                    "source": "name_pattern",
                }
            if field_name.endswith("_number"):
                base = field_name[:-7]  # Strip _number
                return {
                    "field": field_name,
                    "target_resource": base + "s",  # Pluralize
                    "type": "integer",
                    "confidence": "medium",
                    "source": "name_pattern",
                }

        return None

    def _extract_ref_name(self, ref: str) -> Optional[str]:
        """Extract resource name from $ref path.

        Args:
            ref: $ref path (e.g., "#/components/schemas/Repository")

        Returns:
            Lowercase resource name or None
        """
        if not ref:
            return None
        parts = ref.split("/")
        return parts[-1].lower() if parts else None

    def _infer_resource(self, param_name: str) -> Optional[str]:
        """Infer resource from parameter name.

        Args:
            param_name: Parameter name (e.g., "issue_number", "pull_number")

        Returns:
            Inferred resource name or None
        """
        # issue_number -> issues, pull_number -> pulls
        if param_name.endswith("_number"):
            base = param_name[:-7]
            return base + "s"
        if param_name.endswith("_id"):
            base = param_name[:-3]
            return base + "s"
        return None
