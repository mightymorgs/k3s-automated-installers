"""Swagger 2.0 schema adapter.

Handles Swagger 2.0 specifications which differ from OpenAPI 3.0 in several ways:
- Uses #/definitions/ instead of #/components/schemas/
- Uses 'in: body' parameter style instead of requestBody
- Has produces/consumes at operation level (not on individual content types)
- Different parameter locations (body, formData vs requestBody)

This adapter provides:
1. Field reference extraction from #/definitions/ refs
2. Operation reference extraction from body parameters
3. Output extraction from response schemas
4. Conversion to OpenAPI 3.0-style intermediate representation
"""

import re
from typing import Any, Dict, List, Optional

# Swagger 2.0 uses #/definitions/ instead of OpenAPI 3's #/components/schemas/
SWAGGER2_REF_PREFIX = "#/definitions/"
OPENAPI3_REF_PREFIX = "#/components/schemas/"

# Common suffixes to strip when normalizing resource names from refs
REF_SUFFIXES_TO_STRIP = (
    "Request", "Response", "Create", "Update", "Patch",
    "Input", "Output", "Dto", "DTO", "Model", "Schema"
)


def normalize_ref_to_resource(ref: str) -> str:
    """Normalize a $ref path to a resource name.

    Extracts the schema name from #/definitions/SomeName or #/components/schemas/SomeName,
    strips common suffixes, and converts to lowercase.

    Args:
        ref: The $ref string (e.g., "#/definitions/UserRequest")

    Returns:
        Normalized resource name (e.g., "user")
    """
    # Extract the schema name from the ref path
    if ref.startswith(SWAGGER2_REF_PREFIX):
        name = ref[len(SWAGGER2_REF_PREFIX):]
    elif ref.startswith(OPENAPI3_REF_PREFIX):
        name = ref[len(OPENAPI3_REF_PREFIX):]
    else:
        # Just take the last path segment
        name = ref.split("/")[-1]

    # Strip common suffixes
    for suffix in REF_SUFFIXES_TO_STRIP:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[:-len(suffix)]
            break

    return name.lower()


class Swagger2Adapter:
    """Adapter for Swagger 2.0 specifications.

    Provides methods to extract field references, operation references,
    and outputs from Swagger 2.0 schemas, as well as conversion to
    an intermediate representation compatible with the skill generator.
    """

    def __init__(self, service: str, known_resources: Optional[set] = None):
        """Initialize the adapter.

        Args:
            service: Service name for the API (used in skill paths)
            known_resources: Optional set of known resource names for FK resolution
        """
        self.service = service
        self.known_resources = known_resources or set()

    def is_swagger2(self, spec: Dict[str, Any]) -> bool:
        """Check if a specification is Swagger 2.0 format.

        Args:
            spec: The parsed specification dictionary

        Returns:
            True if this is a Swagger 2.0 spec, False otherwise
        """
        return spec.get("swagger", "").startswith("2.")

    def extract_field_refs(
        self,
        schema: Optional[Dict[str, Any]],
        source_resource: str
    ) -> List[Dict[str, Any]]:
        """Extract field references from a Swagger 2.0 schema.

        Walks the schema properties looking for #/definitions/ refs,
        including array items. Handles allOf/oneOf/anyOf combiners.

        Args:
            schema: Swagger 2.0 schema dict, or None
            source_resource: Name of the resource this schema belongs to

        Returns:
            List of dicts with:
                - field: property name that contains the $ref
                - ref: the $ref path (e.g., "#/definitions/User")
                - target_resource: normalized resource name (e.g., "user")
                - type: field type ("array" if array items have $ref)
                - source: always "$ref" for these extractions
        """
        if not schema or not isinstance(schema, dict):
            return []

        refs: List[Dict[str, Any]] = []

        # Handle allOf/oneOf/anyOf by recursing into each sub-schema
        for combiner in ("allOf", "oneOf", "anyOf"):
            if combiner in schema:
                combiner_value = schema[combiner]
                if isinstance(combiner_value, list):
                    for sub_schema in combiner_value:
                        refs.extend(self.extract_field_refs(sub_schema, source_resource))

        # Process properties
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return refs

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            if "$ref" in prop_schema:
                ref_path = prop_schema["$ref"]
                refs.append({
                    "field": prop_name,
                    "ref": ref_path,
                    "target_resource": normalize_ref_to_resource(ref_path),
                    "type": prop_schema.get("type", "object"),
                    "source": "$ref",
                })
            elif prop_schema.get("type") == "array":
                items = prop_schema.get("items", {})
                if isinstance(items, dict) and "$ref" in items:
                    ref_path = items["$ref"]
                    refs.append({
                        "field": prop_name,
                        "ref": ref_path,
                        "target_resource": normalize_ref_to_resource(ref_path),
                        "type": "array",
                        "source": "$ref",
                    })

        return refs

    def extract_operation_refs(
        self,
        operation: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract references from a Swagger 2.0 operation.

        In Swagger 2.0, the request body is defined as a parameter with
        'in: body'. This method extracts refs from body parameter schemas.

        Args:
            operation: Swagger 2.0 operation dict

        Returns:
            List of ref dicts (same structure as extract_field_refs)
        """
        refs: List[Dict[str, Any]] = []

        parameters = operation.get("parameters", [])
        if not isinstance(parameters, list):
            return refs

        for param in parameters:
            if not isinstance(param, dict):
                continue

            # Only process body parameters (Swagger 2.0 style)
            if param.get("in") != "body":
                continue

            param_schema = param.get("schema", {})
            if not isinstance(param_schema, dict):
                continue

            # Direct $ref on body schema
            if "$ref" in param_schema:
                ref_path = param_schema["$ref"]
                refs.append({
                    "field": param.get("name", "body"),
                    "ref": ref_path,
                    "target_resource": normalize_ref_to_resource(ref_path),
                    "type": "object",
                    "source": "$ref",
                })
            else:
                # Inline schema with properties
                refs.extend(self.extract_field_refs(param_schema, source_resource="body"))

        return refs

    def extract_outputs(
        self,
        operation: Dict[str, Any],
        resource: str
    ) -> List[Dict[str, Any]]:
        """Extract output field info from response schemas.

        In Swagger 2.0, responses have a 'schema' field directly
        (not nested under content/mediaType).

        Args:
            operation: Swagger 2.0 operation dict
            resource: Resource name for context

        Returns:
            List of output field dicts with:
                - name: field name
                - type: field type
                - ref: optional $ref if the response uses a reference
                - target_resource: normalized resource name if ref present
        """
        outputs: List[Dict[str, Any]] = []

        responses = operation.get("responses", {})
        if not isinstance(responses, dict):
            return outputs

        # Look for success responses (2xx)
        for status_code, response in responses.items():
            if not isinstance(response, dict):
                continue

            # Only process success responses
            try:
                code_int = int(status_code)
                if code_int < 200 or code_int >= 300:
                    continue
            except (ValueError, TypeError):
                # Handle 'default' or other non-numeric keys
                continue

            response_schema = response.get("schema", {})
            if not isinstance(response_schema, dict):
                continue

            # Response is a $ref
            if "$ref" in response_schema:
                ref_path = response_schema["$ref"]
                outputs.append({
                    "name": resource,
                    "type": "object",
                    "ref": ref_path,
                    "target_resource": normalize_ref_to_resource(ref_path),
                })
            elif "properties" in response_schema:
                # Inline schema with properties - extract key fields
                properties = response_schema["properties"]
                if isinstance(properties, dict):
                    for prop_name, prop_schema in properties.items():
                        if not isinstance(prop_schema, dict):
                            continue
                        output = {
                            "name": prop_name,
                            "type": prop_schema.get("type", "object"),
                        }
                        if "$ref" in prop_schema:
                            output["ref"] = prop_schema["$ref"]
                            output["target_resource"] = normalize_ref_to_resource(prop_schema["$ref"])
                        outputs.append(output)
            elif "type" in response_schema:
                # Simple type response (e.g., array)
                outputs.append({
                    "name": resource,
                    "type": response_schema["type"],
                })

            # Only process first success response
            break

        return outputs

    def to_intermediate(self, swagger2_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Swagger 2.0 spec to OpenAPI 3.0-style intermediate representation.

        This allows the skill generator to use a single code path for processing
        both Swagger 2.0 and OpenAPI 3.0 specs.

        Conversions performed:
        - definitions -> components.schemas
        - produces/consumes -> handled at content level (preserved for reference)
        - body parameters -> requestBody (when processing paths)

        Args:
            swagger2_spec: Swagger 2.0 specification dict

        Returns:
            OpenAPI 3.0-style intermediate representation
        """
        ir: Dict[str, Any] = {}

        # Preserve info section
        if "info" in swagger2_spec:
            ir["info"] = swagger2_spec["info"].copy()

        # Convert definitions to components.schemas
        if "definitions" in swagger2_spec:
            ir["components"] = {
                "schemas": swagger2_spec["definitions"].copy()
            }

        # Preserve paths (conversion of body params happens during processing)
        if "paths" in swagger2_spec:
            ir["paths"] = swagger2_spec["paths"].copy()

        # Preserve security definitions if present
        if "securityDefinitions" in swagger2_spec:
            ir["components"] = ir.get("components", {})
            ir["components"]["securitySchemes"] = swagger2_spec["securityDefinitions"].copy()

        # Store global produces/consumes for reference
        if "produces" in swagger2_spec or "consumes" in swagger2_spec:
            ir["x-swagger2-media-types"] = {
                "produces": swagger2_spec.get("produces", []),
                "consumes": swagger2_spec.get("consumes", []),
            }

        # Mark as converted from Swagger 2.0
        ir["x-converted-from"] = "swagger-2.0"
        ir["openapi"] = "3.0.0"  # Intermediate representation version

        return ir
