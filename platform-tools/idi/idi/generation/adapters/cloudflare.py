"""Cloudflare API adapter for response unwrapping and FK detection.

Handles Cloudflare's response wrapper format:
    {
        "result": { /* actual data */ },
        "success": true,
        "errors": [],
        "messages": []
    }

The default REST adapter sees top-level fields (result, success, errors, messages)
instead of the actual resource fields inside "result". This adapter:

1. Unwraps the "result" field in response schemas so the generator extracts
   real resource fields (id, name, etc.) instead of wrapper fields.
2. Extracts path parameters (account_id, zone_id) as output facts for
   parent-child resource dependency chains.
3. Normalizes deeply nested resource names from Cloudflare's path structure.

Usage:
    adapter = CloudflareAdapter(service="cloudflare")
    # Unwrap response schema before field extraction
    schema = adapter.extract_response_schema(operation, method, path)
    # FK detection (delegates to OpenApiRestAdapter)
    refs = adapter.extract_field_refs(body_schema, resource)
"""

import re
from typing import Any, Dict, List, Optional, Set

from .openapi_rest import OpenApiRestAdapter


# Cloudflare wrapper fields that should NOT appear in response_fields output.
# These are envelope metadata, not resource data.
WRAPPER_FIELDS = frozenset({"result", "success", "errors", "messages", "result_info"})


class CloudflareAdapter(OpenApiRestAdapter):
    """Adapter for Cloudflare API specs.

    Extends OpenApiRestAdapter with:
    - Response schema unwrapping (navigates past result/success/errors envelope)
    - Path parameter extraction as output facts (account_id, zone_id)
    - Resource name normalization for deeply nested paths
    """

    def __init__(self, service: str, known_resources: Optional[Set[str]] = None,
                 spec: Optional[Dict[str, Any]] = None):
        """Initialize Cloudflare adapter.

        Args:
            service: Service name (typically 'cloudflare')
            known_resources: Optional set of known resource names for FK resolution
            spec: Full OpenAPI spec dict (needed for $ref resolution during
                  response schema unwrapping)
        """
        super().__init__(service=service, known_resources=known_resources)
        self._spec = spec or {}

    def extract_response_schema(
        self,
        operation: Dict[str, Any],
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Extract response schema, unwrapping Cloudflare's result envelope.

        Cloudflare wraps all successful responses in::

            {
                "result": { /* actual data */ },
                "success": true,
                "errors": [],
                "messages": []
            }

        This method navigates through allOf compositions and $ref chains to
        find the "result" property, then returns the schema of just the result
        so the generator sees real resource fields (id, name, etc.).

        Args:
            operation: OpenAPI operation object
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /accounts/{account_id}/zones)

        Returns:
            Unwrapped result schema dict, or None if no success response found.
            Falls back to returning the full response schema if no wrapper detected.
        """
        responses = operation.get("responses", {})

        # Try success status codes in order
        success_response = None
        for code in ("200", "201", "202"):
            if code in responses:
                success_response = responses[code]
                break

        if not success_response:
            return None

        # Get content schema (OpenAPI 3.0 style)
        content = success_response.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})

        # Swagger 2.0 fallback
        if not schema and "schema" in success_response:
            schema = success_response["schema"]

        if not schema:
            return None

        # Navigate allOf to find the result property
        result_schema = self._find_result_in_schema(schema)
        if result_schema is not None:
            # Flatten allOf/anyOf in the result schema so the generator
            # always sees a schema with "properties" at top level.
            return self._flatten_schema(result_schema)

        # Fallback: no wrapper detected, return schema as-is
        return self._flatten_schema(schema)

    def _find_result_in_schema(self, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Recursively search for the 'result' property in a schema.

        Handles allOf compositions where the wrapper base and the result
        override are in separate allOf entries.

        Args:
            schema: Schema dict to search

        Returns:
            Schema of the 'result' field, or None if not found.
        """
        # Direct properties check
        if "properties" in schema and "result" in schema["properties"]:
            return schema["properties"]["result"]

        # allOf composition: merge all sub-schemas and check for result
        if "allOf" in schema:
            merged_properties = {}
            for sub in schema["allOf"]:
                if not isinstance(sub, dict):
                    continue
                # Collect properties from this sub-schema
                props = sub.get("properties", {})
                merged_properties.update(props)
                # Also recurse into nested allOf
                if "allOf" in sub:
                    nested = self._find_result_in_schema(sub)
                    if nested is not None:
                        return nested

            if "result" in merged_properties:
                return merged_properties["result"]

        # oneOf / anyOf: check each branch
        for combiner in ("oneOf", "anyOf"):
            if combiner in schema:
                for branch in schema[combiner]:
                    result = self._find_result_in_schema(branch)
                    if result is not None:
                        return result

        return None

    def _flatten_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten allOf/anyOf compositions into a single schema with properties.

        The generator's ``_fields_from_schema`` only handles schemas with a
        top-level ``properties`` key.  Many Cloudflare response schemas use
        allOf/anyOf to compose properties from multiple sub-schemas.  This
        method merges them so the generator can extract fields.

        Args:
            schema: A possibly-composed schema dict.

        Returns:
            A schema dict with ``properties`` merged from all branches.
            Returns the original schema unchanged if it already has properties
            and no allOf/anyOf.
        """
        if not isinstance(schema, dict):
            return schema

        # If it already has properties and no allOf, return as-is
        if "properties" in schema and "allOf" not in schema and "anyOf" not in schema:
            return schema

        merged: Dict[str, Any] = {}

        # Merge from allOf branches
        if "allOf" in schema:
            for sub in schema["allOf"]:
                if not isinstance(sub, dict):
                    continue
                # Recurse into nested compositions
                flattened = self._flatten_schema(sub)
                merged.update(flattened.get("properties", {}))

        # Merge from anyOf branches (take all fields from all branches)
        if "anyOf" in schema:
            for sub in schema["anyOf"]:
                if not isinstance(sub, dict):
                    continue
                flattened = self._flatten_schema(sub)
                merged.update(flattened.get("properties", {}))

        # Also include direct properties
        if "properties" in schema:
            merged.update(schema["properties"])

        if merged:
            return {"type": "object", "properties": merged}

        return schema

    def extract_path_parameters_as_outputs(
        self,
        path: str,
        method: str,
    ) -> Dict[str, str]:
        """Extract path parameters as output facts for create operations.

        For POST (create) operations, the last resource segment in the path
        represents the new resource being created, and its ID is an output fact.

        Examples:
            POST /accounts -> {"facts://cloudflare/accounts#id": "id"}
            POST /accounts/{account_id}/zones -> {"facts://cloudflare/zones#id": "id"}
            POST /zones/{zone_id}/dns_records -> {"facts://cloudflare/dns-records#id": "id"}

        Args:
            path: API path (e.g., /accounts/{account_id}/zones)
            method: HTTP method

        Returns:
            Dict mapping fact URI -> response field name.
            Empty dict for non-POST methods.
        """
        if method.upper() != "POST":
            return {}

        outputs = {}

        # Extract the last non-parameter path segment (the resource being created)
        segments = [s for s in path.split("/") if s]
        non_param_segments = [s for s in segments if not s.startswith("{")]

        if non_param_segments:
            resource = non_param_segments[-1]
            # Normalize: underscores to hyphens for resource name
            resource_normalized = resource.replace("_", "-")
            fact_uri = f"facts://{self.service}/{resource_normalized}#id"
            outputs[fact_uri] = "id"

        return outputs

    def normalize_resource_name(self, path: str) -> str:
        """Normalize resource names from deeply nested Cloudflare paths.

        Cloudflare paths can be deeply nested:
            /accounts/{account_id}/access/apps/{app_id}
            /zones/{zone_id}/dns_records/{dns_record_id}

        Strategy: Use the last 1-2 meaningful (non-parameter) path segments,
        joined with hyphens. Underscores are converted to hyphens.

        Args:
            path: API path

        Returns:
            Normalized resource name (e.g., 'access-apps', 'dns-records')
        """
        # Remove path parameters
        path_clean = re.sub(r"\{[^}]+\}", "", path)
        # Split and filter empty segments
        parts = [p.replace("_", "-") for p in path_clean.split("/") if p]

        if len(parts) >= 2:
            return "-".join(parts[-2:])
        elif len(parts) == 1:
            return parts[0]
        return "unknown"

    @staticmethod
    def is_cloudflare_wrapper_field(field_name: str) -> bool:
        """Check if a field name is part of the Cloudflare response wrapper.

        Args:
            field_name: Response field name to check

        Returns:
            True if this is a wrapper field that should be filtered out
        """
        return field_name.lower() in WRAPPER_FIELDS
