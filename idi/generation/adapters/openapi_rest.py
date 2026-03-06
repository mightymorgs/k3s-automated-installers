"""OpenAPI REST schema adapter for FK detection.

Detects FK relationships using:
1. UUID format fields
2. Integer FK fields (detected by name pattern)
3. $ref schema references
4. CamelCase field names (Sonarr, Radarr, etc.)
"""
import re
from typing import Dict, List, Optional, Any

from idi.generation.fact_model import (
    FactRef,
    ProducedFact,
    normalize_field,
    strip_id_suffix,
    camel_to_snake,
)


# Fields that should never create DEPENDS_ON edges
# These are either pre-existing resources (namespaces) or audit fields
EXCLUDED_FIELDS = frozenset({
    # Kubernetes namespaces - pre-existing resources
    "namespace",
    "namespaces",
    "ns",
    # Timestamp/audit fields
    "created_at",
    "updated_at",
    "modified_at",
    "created_by",
    "updated_by",
})

# FK suffixes that indicate a field references another resource
FK_SUFFIXES = ("_id", "_pk", "_uuid", "_guid", "_uid", "_key", "id")


class OpenApiRestAdapter:
    """Adapter for OpenAPI REST schemas.

    Extracts FK relationships and output facts from OpenAPI schemas.
    Handles both snake_case (Authentik) and camelCase (Sonarr/Radarr) conventions.
    """

    def __init__(self, service: str, known_resources: Optional[set] = None):
        """Initialize adapter for a specific service.

        Args:
            service: Service name (e.g., 'authentik', 'sonarr')
            known_resources: Optional set of known resource names for FK resolution
        """
        self.service = service.lower()
        self.known_resources = known_resources or set()

    def extract_field_refs(
        self,
        schema: Optional[Dict[str, Any]],
        source_resource: str,
    ) -> List[Dict[str, Any]]:
        """Extract FK references from an OpenAPI schema.

        Detects three FK patterns:
        1. $ref schema references
        2. UUID format fields
        3. Integer fields with FK-like names

        Args:
            schema: OpenAPI schema dict (request body schema)
            source_resource: Resource name making the request

        Returns:
            List of dicts with keys:
            - field: Original field name
            - type: Field type (uuid, integer, array, object)
            - source: Detection source ($ref, uuid_format, integer_fk)
            - target_resource: Inferred target resource name (if determinable)
            - ref: $ref path (only if source == "$ref")
        """
        if not schema or not isinstance(schema, dict):
            return []

        refs: List[Dict[str, Any]] = []

        # Handle allOf/oneOf/anyOf by recursing into each sub-schema
        for combiner in ("allOf", "oneOf", "anyOf"):
            if combiner in schema:
                for sub_schema in schema[combiner]:
                    refs.extend(self.extract_field_refs(sub_schema, source_resource))

        # Process properties
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return refs

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            # Skip excluded fields (case-insensitive)
            if prop_name.lower() in EXCLUDED_FIELDS:
                continue

            # 1. Check for $ref (highest priority)
            ref_result = self._check_ref(prop_name, prop_schema)
            if ref_result:
                refs.append(ref_result)
                continue

            # 2. Check for UUID format
            uuid_result = self._check_uuid_format(prop_name, prop_schema)
            if uuid_result:
                refs.append(uuid_result)
                continue

            # 3. Check for integer FK by name pattern
            int_result = self._check_integer_fk(prop_name, prop_schema)
            if int_result:
                refs.append(int_result)
                continue

        return refs

    def _check_ref(self, field_name: str, prop_schema: Dict) -> Optional[Dict]:
        """Check for $ref schema reference."""
        # Direct $ref
        if "$ref" in prop_schema:
            return {
                "field": field_name,
                "ref": prop_schema["$ref"],
                "type": prop_schema.get("type", "object"),
                "source": "$ref",
            }

        # Array with $ref in items
        if prop_schema.get("type") == "array":
            items = prop_schema.get("items", {})
            if isinstance(items, dict) and "$ref" in items:
                return {
                    "field": field_name,
                    "ref": items["$ref"],
                    "type": "array",
                    "source": "$ref",
                }

        return None

    def _check_uuid_format(self, field_name: str, prop_schema: Dict) -> Optional[Dict]:
        """Check for UUID format field."""
        if prop_schema.get("format") == "uuid":
            target = self._infer_target_resource(field_name)
            result = {
                "field": field_name,
                "type": "uuid",
                "source": "uuid_format",
            }
            if target:
                result["target_resource"] = target
            return result
        return None

    def _check_integer_fk(self, field_name: str, prop_schema: Dict) -> Optional[Dict]:
        """Check for integer FK by name pattern.

        Detects fields like:
        - qualityProfileId (CamelCase)
        - group_id (snake_case)
        - provider (if integer type)
        """
        field_type = prop_schema.get("type")
        if field_type != "integer":
            return None

        # Normalize CamelCase to snake_case for analysis
        normalized = normalize_field(field_name)

        # Check if field name suggests a FK relationship
        if self._is_fk_field_name(normalized, field_name):
            target = self._infer_target_resource(field_name)
            result = {
                "field": field_name,
                "type": "integer",
                "source": "integer_fk",
            }
            if target:
                result["target_resource"] = target
            return result

        return None

    def _is_fk_field_name(self, normalized: str, original: str) -> bool:
        """Check if a field name indicates a FK relationship.

        Args:
            normalized: snake_case normalized field name
            original: Original field name (may be camelCase)

        Returns:
            True if field name suggests FK relationship
        """
        # Check for FK suffixes in normalized form
        for suffix in FK_SUFFIXES:
            if normalized.endswith(suffix):
                return True

        # Check for CamelCase Id suffix (qualityProfileId)
        if original.endswith("Id"):
            return True

        return False

    def _infer_target_resource(self, field_name: str) -> Optional[str]:
        """Infer target resource name from field name.

        Examples:
            authorization_flow -> flow
            tunnel_id -> tunnel
            qualityProfileId -> qualityprofile
            provider -> provider
        """
        # Normalize to snake_case
        normalized = normalize_field(field_name)

        # Strip FK suffixes to get base resource name
        target = strip_id_suffix(normalized)

        # Remove underscores to get compact form (quality_profile -> qualityprofile)
        target = target.replace("_", "")

        return target if target else None

    def extract_outputs(
        self,
        response_schema: Optional[Dict[str, Any]],
        resource: str,
        operation: str,
    ) -> List[ProducedFact]:
        """Extract output facts from a response schema.

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

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            # Skip excluded fields
            if prop_name.lower() in EXCLUDED_FIELDS:
                continue

            # Create FactRef for this output
            ref = FactRef(
                service=self.service,
                resource=resource,
                field=prop_name,
            )

            # Build skill path (will be updated by caller if needed)
            skill_path = f"{self.service}/{resource}/{operation}.md"

            outputs.append(ProducedFact(
                ref=ref,
                skill_path=skill_path,
                response_field=prop_name,
                operation=operation,
            ))

        return outputs
