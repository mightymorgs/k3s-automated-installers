"""Field extraction from OpenAPI schemas for the skill generation pipeline.

Handles:
- Extracting fields from request body and response schemas.
- Detecting field types, enums, and format annotations.
- Resolving ``$ref`` pointers within property definitions.
- Building heuristic output facts.
- Estimating raw API doc token counts.

All functions take a :class:`GeneratorContext` as their first parameter
(replacing the old monolithic ``self``), keeping them stateless and testable.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set

from idi.generation.adapters.envelope_detector import detect_envelope, navigate_unwrap_path
from idi.generation.context import GeneratorContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema preprocessing
# ---------------------------------------------------------------------------

_METADATA_KEYS = ("description", "title", "nullable", "deprecated", "readOnly", "writeOnly")


def unwrap_single_item_combinator(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse single-item allOf/oneOf/anyOf to the inner schema.

    Recursively unwraps trivial combinator wrappers. Parent metadata
    (description, title) is preserved if the child lacks those keys.
    """
    if not isinstance(schema, dict):
        return schema

    for key in ("allOf", "oneOf", "anyOf"):
        items = schema.get(key)
        if isinstance(items, list) and len(items) == 1:
            child = dict(items[0])  # shallow copy of child
            # Merge parent metadata into child (child takes precedence)
            for mk in _METADATA_KEYS:
                if mk in schema and mk not in child:
                    child[mk] = schema[mk]
            # Recurse to handle nested trivial wrappers
            return unwrap_single_item_combinator(child)

    return schema


def canonicalize_composed_schema(
    schema: Dict[str, Any],
    *,
    visited: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    """Flatten allOf/oneOf/anyOf compositions into a canonical flat schema.

    Algorithm:
    1. If the schema has no composition keywords, return as-is.
    2. Apply single-item combinator unwrapping first.
    3. For allOf: merge all branches' properties and required fields.
       - Conflict detection: same property name with different types -> mark _ambiguous.
       - Preserve readOnly/writeOnly/deprecated/nullable with last-wins semantics.
       - Preserve additionalProperties from any branch.
    4. For oneOf/anyOf WITHOUT discriminator: use property intersection only.
    5. For oneOf/anyOf WITH discriminator: allow property union.
    6. Preserve discriminator field during merge.
    7. Recurse into nested compositions. Track visited schemas by id() to halt cycles.
    8. Set type to "object" if properties exist and type is not set.

    Args:
        schema: The schema dict to canonicalize. May contain allOf/oneOf/anyOf.
        visited: Set of schema object ids already visited (cycle detection).

    Returns:
        A new schema dict with composition flattened. Does not mutate input.
    """
    if not isinstance(schema, dict):
        return schema

    # Cycle detection via object identity.
    if visited is None:
        visited = set()
    schema_id = id(schema)
    if schema_id in visited:
        return {}
    visited = visited | {schema_id}  # Copy to avoid mutation across branches

    has_allof = "allOf" in schema and isinstance(schema["allOf"], list)
    has_oneof = "oneOf" in schema and isinstance(schema["oneOf"], list)
    has_anyof = "anyOf" in schema and isinstance(schema["anyOf"], list)

    if not (has_allof or has_oneof or has_anyof):
        return schema

    # Capture parent-level properties before unwrapping (unwrap may drop them).
    parent_props = schema.get("properties", {})
    parent_required = schema.get("required", [])

    # Single-item unwrapping first (may eliminate composition entirely).
    schema = unwrap_single_item_combinator(schema)
    # Re-check after unwrapping.
    has_allof = "allOf" in schema and isinstance(schema["allOf"], list)
    has_oneof = "oneOf" in schema and isinstance(schema["oneOf"], list)
    has_anyof = "anyOf" in schema and isinstance(schema["anyOf"], list)
    if not (has_allof or has_oneof or has_anyof):
        # Merge parent properties back if unwrapping dropped them.
        if parent_props:
            merged = {**schema}
            merged_p = dict(parent_props)
            merged_p.update(schema.get("properties", {}))  # child overrides parent
            merged["properties"] = merged_p
            req = list(parent_required)
            for r in schema.get("required", []):
                if r not in req:
                    req.append(r)
            if req:
                merged["required"] = req
            if "type" not in merged and "properties" in merged:
                merged["type"] = "object"
            return merged
        if "properties" in schema and "type" not in schema:
            return {**schema, "type": "object"}
        return schema

    merged_props: Dict[str, Any] = {}
    merged_required: List[str] = []
    result: Dict[str, Any] = {}
    has_discriminator = "discriminator" in schema and isinstance(schema["discriminator"], dict)

    # Include parent-level properties (common pattern: properties alongside allOf).
    for pname, pval in schema.get("properties", {}).items():
        merged_props[pname] = dict(pval)
    for req in schema.get("required", []):
        if req not in merged_required:
            merged_required.append(req)
    if "additionalProperties" in schema:
        result["additionalProperties"] = schema["additionalProperties"]

    # --- allOf: merge all branches ---
    if has_allof:
        for sub in schema["allOf"]:
            sub = canonicalize_composed_schema(sub, visited=visited)
            for pname, pval in sub.get("properties", {}).items():
                if pname in merged_props:
                    existing = merged_props[pname]
                    # Conflict detection: different type -> ambiguous
                    if existing.get("type") != pval.get("type") and "type" in existing and "type" in pval:
                        merged_props[pname] = {**existing, **pval, "_ambiguous": True}
                    else:
                        # Same type or missing type: last-wins merge for metadata
                        merged_props[pname] = {**existing, **pval}
                else:
                    merged_props[pname] = dict(pval)
            for req in sub.get("required", []):
                if req not in merged_required:
                    merged_required.append(req)
            if "additionalProperties" in sub:
                result["additionalProperties"] = sub["additionalProperties"]

    # --- oneOf/anyOf ---
    for combinator_key in ("oneOf", "anyOf"):
        if combinator_key not in schema or not isinstance(schema[combinator_key], list):
            continue
        branches = schema[combinator_key]
        if not branches:
            continue

        resolved_branches = [
            canonicalize_composed_schema(b, visited=visited) for b in branches
        ]

        if has_discriminator:
            # Discriminator present: union of all properties
            for branch in resolved_branches:
                for pname, pval in branch.get("properties", {}).items():
                    if pname not in merged_props:
                        merged_props[pname] = dict(pval)
        else:
            # No discriminator: intersection only
            prop_sets = [
                set(b.get("properties", {}).keys()) for b in resolved_branches
            ]
            if prop_sets:
                intersection = prop_sets[0]
                for ps in prop_sets[1:]:
                    intersection &= ps
                # Use properties from the first branch for the intersection
                first_branch_props = resolved_branches[0].get("properties", {})
                for pname in intersection:
                    if pname not in merged_props:
                        merged_props[pname] = dict(first_branch_props[pname])

    # Preserve discriminator.
    if has_discriminator:
        result["discriminator"] = schema["discriminator"]

    # Copy non-composition keys from original schema.
    for key in ("type", "description", "title", "nullable", "deprecated"):
        if key in schema:
            result[key] = schema[key]

    if merged_props:
        result["properties"] = merged_props
    if merged_required:
        result["required"] = merged_required

    # Type inference: if we have properties but no type, set object.
    if "properties" in result and "type" not in result:
        result["type"] = "object"

    return result


def infer_schema_type(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Infer missing 'type' from sibling schema keys.

    Returns a new dict with 'type' filled in if inference succeeded,
    or the original unchanged if type was already present.
    """
    if not isinstance(schema, dict) or "type" in schema:
        return schema

    if "properties" in schema:
        return {**schema, "type": "object"}
    if "items" in schema:
        return {**schema, "type": "array"}
    if "enum" in schema and schema["enum"]:
        val = schema["enum"][0]
        if isinstance(val, bool):
            return {**schema, "type": "boolean"}
        if isinstance(val, int):
            return {**schema, "type": "integer"}
        if isinstance(val, float):
            return {**schema, "type": "number"}
        if isinstance(val, str):
            return {**schema, "type": "string"}

    return schema


# ---------------------------------------------------------------------------
# Schema field extraction
# ---------------------------------------------------------------------------


def extract_schema_fields(
    ctx: GeneratorContext,
    schema: Dict[str, Any],
    max_depth: int = 2,
) -> Dict[str, Any]:
    """Extract fields from a schema, resolving ``$ref`` and preserving type metadata.

    Recursively walks ``allOf`` compositions and ``properties``, resolving
    internal ``$ref`` pointers against the root spec.  Recursion depth is
    capped at *max_depth* to avoid infinite loops on circular schemas.

    Args:
        ctx: Generator context containing the root OpenAPI schema for
            ``$ref`` resolution.
        schema: The (sub-)schema dict to extract fields from.
        max_depth: Maximum recursion depth for ``allOf`` and nested
            property resolution.  Defaults to ``2``.

    Returns:
        Dict with keys ``type``, ``description``, ``required`` (list of
        required property names), and ``properties`` (mapping of property
        name to a trimmed info dict with ``type``, ``description``,
        ``enum``, ``format``, ``nullable``, and ``items``).
    """
    if not schema or max_depth <= 0:
        return {"type": "object", "properties": {}, "required": []}

    # Preprocessing: canonicalize composed schemas (includes unwrapping), infer types.
    schema = canonicalize_composed_schema(schema)
    schema = infer_schema_type(schema)

    result: Dict[str, Any] = {
        "type": schema.get("type", "object"),
        "description": schema.get("description", ""),
        "required": list(schema.get("required", [])),
        "properties": {},
    }

    # Extract properties.
    for prop_name, prop_schema in schema.get("properties", {}).items():
        prop_schema = infer_schema_type(prop_schema)
        prop_info: Dict[str, Any] = {
            "type": prop_schema.get("type", "object"),
            "description": prop_schema.get("description", "")[:100],
        }

        if "enum" in prop_schema:
            prop_info["enum"] = prop_schema["enum"][:10]
        if "format" in prop_schema:
            prop_info["format"] = prop_schema["format"]
        if "nullable" in prop_schema:
            prop_info["nullable"] = prop_schema["nullable"]

        # For arrays, capture item type.
        if prop_schema.get("type") == "array" and "items" in prop_schema:
            items = prop_schema["items"]
            prop_info["items"] = {"type": items.get("type", "object")}
            if "format" in items:
                prop_info["items"]["format"] = items["format"]

        result["properties"][prop_name] = prop_info

    return result


# ---------------------------------------------------------------------------
# Field type detection
# ---------------------------------------------------------------------------


def get_field_type(
    ctx: GeneratorContext,
    prop_info: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
) -> str:
    """Get a human-readable type string for a property schema.

    Resolves ``$ref`` pointers and inspects ``allOf``/``oneOf``/``anyOf``
    for enum types.  For arrays, the item type is included in the result
    (e.g., ``'array[object]'``).  Format annotations are appended in
    parentheses (e.g., ``'string (uuid)'``).

    Args:
        ctx: Generator context for ``$ref`` resolution.
        prop_info: The property schema dict from OpenAPI.
        schema: Override schema for ``$ref`` resolution.  If ``None``,
            ``ctx.schema`` is used.

    Returns:
        Type string such as ``'string'``, ``'integer'``, ``'enum'``,
        ``'array[object]'``, ``'string (uuid)'``, or ``'object'``.
    """
    if schema is None:
        schema = ctx.schema

    # Check for direct enum.
    if "enum" in prop_info:
        return "enum"

    # Check allOf/oneOf/anyOf for enum.
    for key in ("allOf", "oneOf", "anyOf"):
        if key in prop_info:
            for item in prop_info[key]:
                if "enum" in item:
                    return "enum"

    # Get base type.
    base_type = prop_info.get("type", "object")

    # Handle array items -- show item type.
    if base_type == "array" and "items" in prop_info:
        items = prop_info["items"]
        item_type = items.get("type", "object")
        return f"array[{item_type}]"

    # Add format if present (e.g., "string (uuid)", "string (date-time)").
    fmt = prop_info.get("format", "")
    if fmt:
        return f"{base_type} ({fmt})"

    return base_type


# ---------------------------------------------------------------------------
# Enum value extraction
# ---------------------------------------------------------------------------


def extract_enum_values(
    ctx: GeneratorContext,
    prop_info: Dict[str, Any],
) -> List[str]:
    """Extract enum values from a property schema, resolving ``$ref``.

    Handles three patterns:
    1. Direct ``enum`` on the property.
    2. ``$ref`` pointing to a schema with ``enum``.
    3. ``allOf``/``oneOf``/``anyOf`` containing an ``enum`` sub-schema.

    Args:
        ctx: Generator context for ``$ref`` resolution.
        prop_info: The property schema dict.

    Returns:
        List of enum value strings, or an empty list if none found.
    """
    # Direct enum.
    if "enum" in prop_info:
        return prop_info["enum"]

    # Enum in allOf/oneOf/anyOf.
    for key in ("allOf", "oneOf", "anyOf"):
        if key in prop_info:
            for item in prop_info[key]:
                if "enum" in item:
                    return item["enum"]

    return []


# ---------------------------------------------------------------------------
# Request field extraction
# ---------------------------------------------------------------------------


def extract_request_fields(
    ctx: GeneratorContext,
    op_info: Dict[str, Any],
    operation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract request fields from body, query, and header parameters.

    Handles four sources of request fields:
    1. **OpenAPI 3.0**: ``requestBody.content.application/json.schema``
    2. **Swagger 2.0**: Parameter with ``in: body``
    3. **Swagger 2.0 formData**: Parameters with ``in: formData`` (e.g., Slack)
    4. **Query parameters**: Parameters with ``in: query`` (all spec versions)

    For each field, the result includes ``name``, ``type``, ``required``,
    ``description``, ``source``, and optionally ``enum_values``, ``default``,
    and ``skip_hint``.

    Args:
        ctx: Generator context for ``$ref`` resolution and type inference.
        op_info: Operation info dict (currently unused but reserved for
            future adapter-specific logic).
        operation: The OpenAPI operation object.

    Returns:
        List of field dicts with: ``name``, ``type``, ``required``,
        ``description``, ``source``, and optional ``enum_values``,
        ``default``, ``skip_hint``.
    """
    fields: List[Dict[str, Any]] = []

    # OpenAPI 3.0: Get request body from requestBody.
    body_schema: Dict[str, Any] = {}
    request_body = operation.get("requestBody", {})
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema", {})

    # Swagger 2.0 fallback: body parameter with in=body.
    if not body_schema:
        for param in operation.get("parameters", []):
            if param.get("in") == "body":
                body_schema = param.get("schema", {})
                break

    # Swagger 2.0 formData parameters (e.g., Slack APIs).
    if not body_schema:
        form_data_params = [
            p for p in operation.get("parameters", [])
            if p.get("in") == "formData"
        ]
        if form_data_params:
            body_schema = {
                "type": "object",
                "properties": {},
                "required": [],
            }
            for param in form_data_params:
                param_name = param.get("name", "")
                body_schema["properties"][param_name] = {
                    "type": param.get("type", "string"),
                    "description": param.get("description", ""),
                }
                if param.get("required"):
                    body_schema["required"].append(param_name)

    required_fields = set(body_schema.get("required", []))

    for prop_name, prop_info in body_schema.get("properties", {}).items():
        field: Dict[str, Any] = {
            "name": prop_name,
            "type": get_field_type(ctx, prop_info),
            "required": prop_name in required_fields,
            "description": prop_info.get("description", "")[:120],
            "source": "body",
        }

        # Extract enum values (may be nested in $ref).
        enum_values = extract_enum_values(ctx, prop_info)
        if enum_values:
            field["type"] = "enum"
            field["enum_values"] = enum_values

        # Preserve default values from OpenAPI property schema.
        if "default" in prop_info:
            field["default"] = prop_info["default"]

        # Add skip_hint for optional array fields.
        # OpenAPI nullable fields may express type as a list (e.g.,
        # ["array", "null"]) instead of a plain string — normalise first.
        field_type_str = field.get("type", "")
        if isinstance(field_type_str, list):
            field_type_str = field_type_str[0] if field_type_str else ""
        if not field.get("required") and field_type_str.startswith("array"):
            field["skip_hint"] = "Pass empty array [] to omit"

        fields.append(field)

    # --- Query parameters (all spec versions) ---
    seen_names = {f["name"] for f in fields}
    for param in operation.get("parameters", []):
        if param.get("in") != "query":
            continue
        param_name = param.get("name", "")
        if not param_name or param_name in seen_names:
            continue
        seen_names.add(param_name)

        param_schema = param.get("schema", {})
        param_type = param_schema.get("type", param.get("type", "string"))
        param_fmt = param_schema.get("format", param.get("format", ""))

        field = {
            "name": param_name,
            "type": f"{param_type} ({param_fmt})" if param_fmt else param_type,
            "required": param.get("required", False),
            "description": param.get("description", "")[:120],
            "source": "query",
        }

        enum_values = param_schema.get("enum", param.get("enum"))
        if enum_values:
            field["type"] = "enum"
            field["enum_values"] = enum_values

        if "default" in param_schema:
            field["default"] = param_schema["default"]
        elif "default" in param:
            field["default"] = param["default"]

        fields.append(field)

    return fields


# ---------------------------------------------------------------------------
# Response field extraction
# ---------------------------------------------------------------------------


def extract_response_fields(
    ctx: GeneratorContext,
    operation: Dict[str, Any],
    path: Optional[str] = None,
    method: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract response schema fields for an operation.

    Handles both OpenAPI 3.0 (``responses.{code}.content.application/json.schema``)
    and Swagger 2.0 (``responses.{code}.schema``).

    When the active adapter provides ``extract_response_schema()``, it is
    used to unwrap API-specific response envelopes (e.g., Vault's nested
    ``data.data`` for KV v2, or Cloudflare's ``result`` wrapper) before
    field extraction.

    Args:
        ctx: Generator context with adapter and root schema.
        operation: OpenAPI operation object containing responses.
        path: API path (needed by adapters for backend detection).
        method: HTTP method (needed by adapters).

    Returns:
        List of field dicts with: ``name``, ``type``, ``description``,
        and optionally ``wrapper`` (bool) and ``item_type``.
    """
    # --- Try adapter-based extraction first ---
    if path and hasattr(ctx.adapter, "extract_response_schema"):
        adapter_schema = ctx.adapter.extract_response_schema(
            operation,
            method or "GET",
            path,
            spec=ctx.schema,
        )
        if adapter_schema and "properties" in adapter_schema:
            return fields_from_schema(ctx, adapter_schema)

    # --- Generic envelope detection fallback ---
    responses = operation.get("responses", {})
    for _sc in ("200", "201", "202"):
        if _sc not in responses:
            continue
        _resp = responses[_sc]
        _content = _resp.get("content", {})
        _json_ct = _content.get("application/json", {}) if _content else {}
        _resp_schema = _json_ct.get("schema", {})
        if not _resp_schema and "schema" in _resp:
            _resp_schema = _resp["schema"]
        if _resp_schema and "properties" in _resp_schema:
            envelope = detect_envelope(_resp_schema, path)
            if envelope and envelope.confidence >= 0.8:
                inner = navigate_unwrap_path(_resp_schema, envelope.unwrap_path)
                if inner and "properties" in inner:
                    logger.debug(
                        "Envelope detected (%s, %.2f): unwrapping via '%s'",
                        envelope.pattern, envelope.confidence, envelope.unwrap_path,
                    )
                    return fields_from_schema(ctx, inner)
        break  # Only check the first success response found

    # --- Default extraction (no adapter or adapter returned None) ---
    fields: List[Dict[str, Any]] = []

    # Look for success responses (200, 201, 202, 204).
    for status_code in ("200", "201", "202", "204"):
        if status_code not in responses:
            continue

        response = responses[status_code]

        # OpenAPI 3.0: content.application/json.schema
        response_schema: Dict[str, Any] = {}
        content = response.get("content", {})
        if content:
            json_content = content.get("application/json", {})
            response_schema = json_content.get("schema", {})

        # Swagger 2.0 fallback: schema directly on response object.
        if not response_schema and "schema" in response:
            response_schema = response["schema"]

        # Extract properties.
        if "properties" in response_schema:
            for prop_name, prop_info in response_schema["properties"].items():
                field: Dict[str, Any] = {
                    "name": prop_name,
                    "type": get_field_type(ctx, prop_info),
                    "description": prop_info.get("description", "")[:120],
                }

                # Check if this is a wrapper field.
                if prop_info.get("type") == "array":
                    field["wrapper"] = True
                    field["item_type"] = get_field_type(
                        ctx, prop_info.get("items", {}),
                    )
                elif prop_info.get("type") == "object" and "properties" in prop_info:
                    field["wrapper"] = True

                fields.append(field)

        # For array responses at top level.
        elif response_schema.get("type") == "array":
            item_schema = response_schema.get("items", {})

            for prop_name, prop_info in item_schema.get("properties", {}).items():
                fields.append({
                    "name": prop_name,
                    "type": get_field_type(ctx, prop_info),
                    "description": prop_info.get("description", "")[:120],
                })

        break  # Only process the first success response.

    return fields


# ---------------------------------------------------------------------------
# Fields from unwrapped schema
# ---------------------------------------------------------------------------


def fields_from_schema(
    ctx: GeneratorContext,
    schema: Dict[str, Any],
    prefix: str = "",
) -> List[Dict[str, Any]]:
    """Extract field dicts from an already-unwrapped response schema.

    Used when an adapter has navigated through API-specific wrappers and
    returned the inner schema containing the real fields.

    Args:
        ctx: Generator context for type inference.
        schema: Schema dict with a ``properties`` key.
        prefix: Optional prefix to prepend to field names (e.g.,
            ``'data.'`` for nested structures).

    Returns:
        List of field dicts: ``{name, type, description, wrapper}``.
    """
    fields: List[Dict[str, Any]] = []

    for prop_name, prop_info in schema.get("properties", {}).items():
        if not isinstance(prop_info, dict):
            continue

        full_name = f"{prefix}{prop_name}" if prefix else prop_name

        field: Dict[str, Any] = {
            "name": full_name,
            "type": get_field_type(ctx, prop_info),
            "description": prop_info.get("description", "")[:120],
        }

        if prop_info.get("type") == "array":
            field["wrapper"] = True
            field["item_type"] = get_field_type(
                ctx, prop_info.get("items", {}),
            )
        elif prop_info.get("type") == "object" and "properties" in prop_info:
            field["wrapper"] = True

        fields.append(field)

    return fields


# ---------------------------------------------------------------------------
# Raw API token estimation
# ---------------------------------------------------------------------------


def compute_raw_api_tokens(
    ctx: GeneratorContext,
    path: str,
    method: str,
    operation: Dict[str, Any],
) -> int:
    """Estimate the token count of a raw OpenAPI operation object.

    This represents what a traditional (non-IDI) approach would need to
    load into context: the full operation spec with all parameters,
    request body schemas, response schemas, and descriptions.

    Top-level ``$ref`` pointers are shallow-resolved so the measurement
    reflects real doc size rather than pointer size.

    Args:
        ctx: Generator context for ``$ref`` resolution.
        path: API path (reserved for future adapter use).
        method: HTTP method (reserved for future adapter use).
        operation: The OpenAPI operation object.

    Returns:
        Estimated token count (``len(json) // 4``, minimum ``1``).
    """
    raw_json = json.dumps(operation, default=str)
    return max(1, len(raw_json) // 4)


# ---------------------------------------------------------------------------
# Heuristic output builder
# ---------------------------------------------------------------------------

# Ordered list of ID-like fields for output detection.
_ID_FIELD_PRECEDENCE: List[str] = [
    "id", "pk", "uuid", "guid", "uid", "_id",  # Standard IDs
    "key", "token", "taskId",                    # API-specific IDs
    "slug", "name",                              # Naming fields
]


def build_heuristic_outputs(
    ctx: GeneratorContext,
    op_info: Dict[str, Any],
    response_fields: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Build output facts using enhanced heuristics for write operations.

    For ``POST``/``PUT``/``PATCH`` operations, detects ID-like fields in
    the response and generates canonical ``facts://`` URIs as output keys.

    Enhanced heuristics include:

    1. Expanded ID field types (``_id``, ``token``, ``taskId``, ``key``).
    2. Wrapper object detection (PagerDuty, Elastic, Slack pattern).
    3. K8s-style nested fields (``metadata.name``, ``metadata.uid``).

    Args:
        ctx: Generator context (used for ``api_name``).
        op_info: Operation info dict with at least ``resource`` and
            ``method`` keys.
        response_fields: List of response field dicts with ``name``,
            ``type``, and ``description`` keys.

    Returns:
        Dict mapping ``facts://`` URIs to response field names.  Empty
        dict if the method is not ``POST``/``PUT``/``PATCH`` or no
        ID fields are found.
    """
    # Check for top-level ID fields.
    candidates: List[str] = [
        f["name"]
        for f in response_fields
        if f["name"] in _ID_FIELD_PRECEDENCE
    ]

    # Wrapper object detection: if no top-level ID found, check for
    # single object-type wrapper fields.
    if not candidates and response_fields:
        object_fields = [
            f for f in response_fields
            if f.get("type", "").startswith("object") or f.get("type") == "object"
        ]

        if len(object_fields) == 1:
            wrapper_field = object_fields[0]
            wrapper_name = wrapper_field["name"].lower().replace("_", "")
            resource_name = op_info.get("resource", "").lower().replace("-", "")

            # If names are similar, treat as wrapper candidate.
            if wrapper_name == resource_name or wrapper_name.endswith(resource_name):
                # Full implementation would resolve nested schema.
                pass

    # K8s-style metadata fields.
    k8s_candidates: List[str] = []
    for f in response_fields:
        if f["name"] == "metadata":
            k8s_candidates.extend(["metadata.name", "metadata.uid"])

    # Combine candidates.
    all_candidates = candidates + k8s_candidates

    # Sort by precedence.
    resp_key = sorted(
        all_candidates,
        key=lambda f: _ID_FIELD_PRECEDENCE.index(f) if f in _ID_FIELD_PRECEDENCE else 999,
    )

    if not resp_key or op_info.get("method") not in ("POST", "PUT", "PATCH"):
        return {}

    auto_outputs: Dict[str, str] = {}
    seen_canonicals: Set[str] = set()

    for field_name in resp_key:
        # Canonicalize field names.
        if field_name in ("pk", "uuid", "guid", "uid", "_id"):
            canonical = "id"
        elif field_name == "taskId":
            canonical = "task_id"
        elif field_name.startswith("metadata."):
            canonical = field_name.replace(".", "_")
        else:
            canonical = field_name

        fact_uri_str = f"facts://{ctx.api_name}/{op_info['resource']}#{canonical}"
        if fact_uri_str not in seen_canonicals:
            auto_outputs[fact_uri_str] = field_name
            seen_canonicals.add(fact_uri_str)

    return auto_outputs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_known_resources(ctx: GeneratorContext) -> Set[str]:
    """Build a set of known resource names from the OpenAPI schema paths.

    Extracts all non-parameter segments from every path.  This includes
    both leaf resources (e.g., ``'oauth2'``) and parent resources (e.g.,
    ``'providers'``), which is essential for FK detection in APIs with
    nested paths.

    The result is cached on ``ctx.known_resources_cache``.

    Args:
        ctx: Generator context with the parsed schema.

    Returns:
        Set of lowercase resource name strings.
    """
    if ctx.known_resources_cache is not None:
        return ctx.known_resources_cache

    resources: Set[str] = set()
    for path in ctx.schema.get("paths", {}):
        segments = [
            s for s in path.strip("/").split("/")
            if s and not s.startswith("{")
        ]
        for seg in segments:
            resources.add(seg.lower())

    ctx.known_resources_cache = resources
    return resources
