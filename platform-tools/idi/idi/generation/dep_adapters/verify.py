"""Programmatic gates for filtering false positive dependency edges.

Each gate evaluates a single spec-derived signal and returns a GateResult
indicating whether the edge should be kept or killed. Gates run after
adapter merge/dedup/threshold filtering but before final output.

All signals are derived from the OpenAPI spec — no hand-crafted field
name lists or curated verb sets.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of applying a gate to a dependency edge."""

    gate: str
    keep: bool
    reason: str


_NON_ID_FORMATS: frozenset[str] = frozenset({
    "date", "date-time", "email", "uri", "ipv4", "ipv6",
    "byte", "binary", "password",
})

_ID_FIELD_NAMES: frozenset[str] = frozenset({
    "id", "uuid", "slug", "key", "name", "pk", "uid", "identifier",
})

_PATH_PARAM_RE = re.compile(r"\{(\w+)\}")


# ── Identifier index pre-computation ─────────────────────────────────


def build_identifier_index(
    spec: dict[str, Any],
    skill_paths: dict[str, dict],
) -> dict[str, set[str]]:
    """Build a map of resource -> set of identifier field names.

    Extracts identifiers from:
    1. Response schemas of GET/LIST operations (id, uuid, pk, key, slug,
       name fields, and fields ending with ``_id``)
    2. Path parameters adjacent to the resource segment
    """
    from idi.generation.dep_adapters.target_inference import _COMMON_FK_SUFFIXES

    index: dict[str, set[str]] = {}

    for sp_key, sp_val in skill_paths.items():
        parts = sp_key.split("/")
        if len(parts) != 3:
            continue
        _service, resource, op_type = parts

        if resource not in index:
            index[resource] = set()

        # --- Response schema identifiers ---
        if op_type in ("list", "retrieve"):
            endpoint = sp_val.get("endpoint", "")
            method = sp_val.get("method", "")
            if endpoint and method:
                resp_schema = _get_target_response_schema(spec, endpoint, method)
                if resp_schema:
                    resp_schema = _resolve_schema(spec, resp_schema)
                    for fname, fschema in resp_schema.get("properties", {}).items():
                        resolved = _resolve_schema(spec, fschema) if isinstance(fschema, dict) else {}
                        fname_lower = fname.lower()
                        is_id_name = (
                            fname_lower in _ID_FIELD_NAMES
                            or fname_lower.endswith("_id")
                        )
                        has_id_format = resolved.get("format") in ("uuid", "int64", "int32")
                        if is_id_name or has_id_format:
                            index[resource].add(fname_lower)

        # --- Path parameter identifiers ---
        endpoint = sp_val.get("endpoint", "")
        if endpoint:
            segments = endpoint.strip("/").split("/")
            for i, seg in enumerate(segments):
                # Check if this segment is the resource name or a variant
                seg_lower = seg.lower().rstrip("/")
                if seg_lower == resource or seg_lower == resource.replace("-", ""):
                    # Next segment is the resource's path param
                    if i + 1 < len(segments):
                        param_match = _PATH_PARAM_RE.match(segments[i + 1])
                        if param_match:
                            param_name = param_match.group(1).lower()
                            index[resource].add(param_name)
                            # Also add stripped form
                            for suffix in _COMMON_FK_SUFFIXES:
                                stripped = param_name.removesuffix(suffix)
                                if stripped != param_name and stripped:
                                    index[resource].add(stripped)
                                    break

    return index


# ── Field schema resolution ─────────────────────────────────────────


def _resolve_field_schema(
    dep: Dependency,
    operation: OperationInfo,
    spec: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve the consumer field's schema from the operation or spec."""
    source = dep.source

    # Try source-specific lookup first
    if "body" in source:
        schema = _lookup_body_field(dep.field, operation.body_schema)
        if schema is not None:
            return schema
    elif "query" in source:
        schema = _lookup_query_param(dep.field, operation.query_params)
        if schema is not None:
            return schema
    elif "path" in source:
        schema = operation.path_param_schemas.get(dep.field)
        if schema is not None:
            return schema

    # Fallback: try all sources
    schema = _lookup_body_field(dep.field, operation.body_schema)
    if schema is not None:
        return schema
    schema = _lookup_query_param(dep.field, operation.query_params)
    if schema is not None:
        return schema
    schema = operation.path_param_schemas.get(dep.field)
    if schema is not None:
        return schema

    return None


def _lookup_body_field(
    field_name: str, body_schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Look up a field in the body schema properties."""
    props = body_schema.get("properties", {})
    return props.get(field_name)


def _lookup_query_param(
    field_name: str, query_params: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Look up a field in the query parameters."""
    for param in query_params:
        if param.get("name") == field_name:
            # OAS3: schema is nested; Swagger 2.0: type on param directly
            return param.get("schema", param)
    return None


# ── Gate G1: Non-ID Format Block ─────────────────────────────────────


def gate_g1_non_id_format(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G1: Non-ID Format Block — kill fields with non-identifier formats."""
    if field_schema is None:
        return GateResult("G1", True, "no schema")

    fmt = field_schema.get("format", "")
    if fmt and fmt.lower() in _NON_ID_FORMATS:
        return GateResult("G1", False, f"format={fmt}")
    return GateResult("G1", True, "format ok")


# ── Gate G2: Enum Block ──────────────────────────────────────────────


def gate_g2_enum(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G2: Enum Block — kill fields with enum constraints."""
    if field_schema is None:
        return GateResult("G2", True, "no schema")

    if field_schema.get("enum"):
        return GateResult("G2", False, f"enum present")
    return GateResult("G2", True, "no enum")


# ── Gate G4: Non-Scalar Block ────────────────────────────────────────


def gate_g4_non_scalar(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G4: Non-Scalar Block — kill boolean, object, and plain-string arrays."""
    if field_schema is None:
        return GateResult("G4", True, "no schema")

    field_type = field_schema.get("type", "")

    if field_type == "boolean":
        return GateResult("G4", False, "type=boolean")
    if field_type == "object":
        return GateResult("G4", False, "type=object")
    if field_type == "array":
        items = field_schema.get("items", {})
        items_type = items.get("type", "")
        items_format = items.get("format", "")
        # Integer arrays are common FK ID lists — always pass
        if items_type == "integer":
            return GateResult("G4", True, "array of integers")
        # UUID string arrays are FK refs — pass
        if items_type == "string" and items_format == "uuid":
            return GateResult("G4", True, "array of uuid strings")
        # Plain string arrays (CIDR lists, header lists) — kill
        if items_type == "string":
            return GateResult("G4", False, "array of plain strings")
        # Arrays of unknown/complex types — kill
        return GateResult("G4", False, f"array of {items_type or 'unknown'}")

    return GateResult("G4", True, f"type={field_type}")


# ── Gate G3: Bounded Value Detector ──────────────────────────────────


def gate_g3_bounded_value(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G3: Bounded Value Detector — kill bounded integers/numbers (config values, not IDs)."""
    if field_schema is None:
        return GateResult("G3", True, "no schema")

    field_type = field_schema.get("type", "")
    if field_type not in ("integer", "number"):
        return GateResult("G3", True, f"type={field_type}")

    signals: list[str] = []

    # Tight maximum (real DB IDs don't cap at 100 or 1000)
    maximum = field_schema.get("maximum")
    if maximum is not None and isinstance(maximum, (int, float)) and maximum < 10000:
        signals.append(f"max={maximum}")

    exclusive_max = field_schema.get("exclusiveMaximum")
    if exclusive_max is not None and isinstance(exclusive_max, (int, float)) and exclusive_max < 10000:
        signals.append(f"exclusiveMax={exclusive_max}")

    # Default present (FK IDs rarely have defaults like 0 or 30)
    if "default" in field_schema:
        signals.append(f"default={field_schema['default']}")

    # minimum alone is NOT a signal (common FK validation: minimum: 1)

    if signals:
        return GateResult("G3", False, f"bounded: {', '.join(signals)}")
    return GateResult("G3", True, "numeric but unbounded")


# ── Gate G5: Producer-Consumer Type Verification ─────────────────────

# Types interchangeable for identifier references.
_ID_COMPATIBLE_TYPES: frozenset[str] = frozenset({"string", "integer", "number"})


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a JSON Pointer $ref string to its schema dict."""
    if not ref.startswith("#/"):
        return {}
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        if isinstance(node, dict):
            node = node.get(part, {})
        else:
            return {}
    return node if isinstance(node, dict) else {}


def _resolve_schema(
    spec: dict[str, Any], schema: dict[str, Any], depth: int = 0,
) -> dict[str, Any]:
    """Recursively resolve $ref and allOf in a schema."""
    if depth > 10:
        return schema
    if "$ref" in schema:
        return _resolve_schema(spec, _resolve_ref(spec, schema["$ref"]), depth + 1)
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for sub in schema["allOf"]:
            resolved = _resolve_schema(spec, sub, depth + 1)
            for k, v in resolved.items():
                if k == "properties" and "properties" in merged:
                    merged["properties"].update(v)
                elif k == "required" and "required" in merged:
                    merged["required"] = list(set(merged["required"]) | set(v))
                else:
                    merged[k] = v
        return merged
    return schema


def _get_target_response_schema(
    spec: dict[str, Any], endpoint: str, method: str,
) -> dict[str, Any] | None:
    """Look up an endpoint in the spec and extract its response schema."""
    import re
    paths = spec.get("paths", {})
    method_lower = method.lower()

    # Direct match, then fuzzy
    candidates = [endpoint]
    alt = endpoint.rstrip("/") + "/" if not endpoint.endswith("/") else endpoint.rstrip("/")
    candidates.append(alt)

    operation_obj = None
    for candidate in candidates:
        path_item = paths.get(candidate)
        if path_item and method_lower in path_item:
            operation_obj = path_item[method_lower]
            break

    if operation_obj is None:
        # Fuzzy: normalize path params
        norm = re.sub(r"\{[^}]+\}", "{}", endpoint)
        for spec_path, path_item in paths.items():
            if re.sub(r"\{[^}]+\}", "{}", spec_path) == norm and method_lower in path_item:
                operation_obj = path_item[method_lower]
                break

    if operation_obj is None:
        return None

    # Extract response schema from 200/201/202
    responses = operation_obj.get("responses", {})
    is_swagger2 = spec.get("swagger", "").startswith("2")
    for code in ("200", "201", "202"):
        resp = responses.get(code)
        if not resp:
            continue
        if is_swagger2:
            schema = resp.get("schema", {})
            if schema:
                resolved = _resolve_schema(spec, schema)
                if resolved.get("type") == "array" and "items" in resolved:
                    return _resolve_schema(spec, resolved["items"])
                return resolved
        else:
            for _ct, ct_val in resp.get("content", {}).items():
                schema = ct_val.get("schema", {})
                if schema:
                    resolved = _resolve_schema(spec, schema)
                    if resolved.get("type") == "array" and "items" in resolved:
                        return _resolve_schema(spec, resolved["items"])
                    props = resolved.get("properties", {})
                    if "results" in props:
                        results_schema = _resolve_schema(spec, props["results"])
                        if results_schema.get("type") == "array" and "items" in results_schema:
                            return _resolve_schema(spec, results_schema["items"])
                    return resolved
    return None


def _extract_response_id_types(
    spec: dict[str, Any], response_schema: dict[str, Any],
) -> set[str]:
    """Extract types of identifier fields from a response schema."""
    types: set[str] = set()
    props = response_schema.get("properties", {})
    for fname, fschema in props.items():
        resolved = _resolve_schema(spec, fschema)
        fname_lower = fname.lower()
        is_id_name = fname_lower in _ID_FIELD_NAMES or fname_lower.endswith("_id")
        has_id_format = resolved.get("format") in ("uuid", "int64", "int32")
        if is_id_name or has_id_format:
            t = resolved.get("type", "")
            if t:
                types.add(t)
    return types


def gate_g5_producer_consumer(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G5: Producer-Consumer Type Verification — kill on type incompatibility."""
    if field_schema is None:
        return GateResult("G5", True, "no schema")

    consumer_type = field_schema.get("type", "")
    if not consumer_type:
        return GateResult("G5", True, "consumer type unknown")

    if skill_paths is None:
        return GateResult("G5", True, "no skill_paths")

    # Find target resource operations
    target_resource = dep.target_resource
    service = operation.service
    produced_types: set[str] = set()

    for op_name in ("create", "list", "retrieve"):
        sp_key = f"{service}/{target_resource}/{op_name}"
        sp_val = skill_paths.get(sp_key)
        if sp_val is None:
            continue
        endpoint = sp_val.get("endpoint", "")
        method = sp_val.get("method", "")
        if not endpoint or not method:
            continue
        resp_schema = _get_target_response_schema(spec, endpoint, method)
        if resp_schema:
            produced_types |= _extract_response_id_types(spec, resp_schema)

    if not produced_types:
        return GateResult("G5", True, "no producer ID types found")

    # Direct type match
    if consumer_type in produced_types:
        return GateResult("G5", True, f"type match: {consumer_type}")

    # ID-compatible coercion (string/integer/number are interchangeable)
    if consumer_type in _ID_COMPATIBLE_TYPES and produced_types & _ID_COMPATIBLE_TYPES:
        return GateResult("G5", True, f"type coercible: {consumer_type} vs {produced_types}")

    return GateResult("G5", False,
                      f"type mismatch: consumer={consumer_type}, producers={produced_types}")


# ── Gate G6: Query Filter Quarantine ─────────────────────────────────


def gate_g6_query_filter(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G6: Query Filter Quarantine — kill optional query params on GET endpoints."""
    # Only applies to query-sourced deps
    if "query" not in dep.source:
        return GateResult("G6", True, "not a query param")

    # Only applies to GET endpoints
    if operation.method.upper() != "GET":
        return GateResult("G6", True, f"method={operation.method}")

    # Look up the param in operation.query_params to check required
    for param in operation.query_params:
        if param.get("name") == dep.field:
            if not param.get("required", False):
                return GateResult("G6", False, "optional query param on GET")
            return GateResult("G6", True, "required query param")

    return GateResult("G6", True, "param not found in query_params")


# ── Gate G7: CRUD Signature Gate ─────────────────────────────────────


def gate_g7_crud_signature(
    dep: Dependency,
    field_schema: dict[str, Any] | None,
    spec: dict[str, Any],
    operation: OperationInfo,
    skill_paths: dict[str, dict] | None,
) -> GateResult:
    """G7: CRUD Signature Gate — kill edges to POST-only targets with no outputs."""
    if skill_paths is None:
        return GateResult("G7", True, "no skill_paths")

    target_resource = dep.target_resource
    service = dep.target_service or operation.service
    prefix = f"{service}/{target_resource}/"

    # Find all operations for the target resource
    target_ops = {k: v for k, v in skill_paths.items() if k.startswith(prefix)}
    if not target_ops:
        return GateResult("G7", True, "target not in skill_paths")

    # Check for list/retrieve/any GET
    if f"{prefix}list" in target_ops:
        return GateResult("G7", True, "target has list")
    if f"{prefix}retrieve" in target_ops:
        return GateResult("G7", True, "target has retrieve")
    for _key, val in target_ops.items():
        if val.get("method", "").upper() == "GET":
            return GateResult("G7", True, "target has GET operation")

    # POST-only target — check if create produces identifiers
    create_key = f"{prefix}create"
    create_val = target_ops.get(create_key)
    if create_val:
        endpoint = create_val.get("endpoint", "")
        method = create_val.get("method", "")
        if endpoint and method:
            resp_schema = _get_target_response_schema(spec, endpoint, method)
            if resp_schema:
                id_types = _extract_response_id_types(spec, resp_schema)
                if id_types:
                    return GateResult("G7", True, "POST-only but produces IDs")

    ops_list = [k.split("/")[-1] for k in target_ops]
    return GateResult("G7", False, f"POST-only, no IDs: {ops_list}")


# ── Gate registry ────────────────────────────────────────────────────

_GATES = [
    gate_g4_non_scalar,
    gate_g1_non_id_format,
    gate_g2_enum,
    gate_g3_bounded_value,
    gate_g5_producer_consumer,
    gate_g6_query_filter,
    gate_g7_crud_signature,
]


# ── Fan-out suppression ──────────────────────────────────────────────

# Penalty multiplier for non-FK-suffixed fields in high-fan-out groups.
_FAN_OUT_PENALTY = 0.2
_FAN_OUT_THRESHOLD = 3


def suppress_fan_out(deps: list[Dependency]) -> list[Dependency]:
    """Penalize non-FK-suffixed fields in high-fan-out target groups.

    When 3+ body FK edges point to the same target and strictly >50% lack
    FK suffixes, apply a penalty to all non-FK-suffixed fields in the group.
    FK-suffixed fields are preserved. Non-body sources are excluded.
    """
    from idi.generation.dep_adapters.target_inference import _has_fk_suffix

    # Group body deps by target_resource.
    body_groups: dict[str, list[int]] = {}
    for i, dep in enumerate(deps):
        if dep.source == "generic_odg:body":
            body_groups.setdefault(dep.target_resource, []).append(i)

    # Identify indices to penalize.
    penalize: set[int] = set()
    for _target, indices in body_groups.items():
        if len(indices) < _FAN_OUT_THRESHOLD:
            continue
        fk_count = sum(
            1 for i in indices if _has_fk_suffix(deps[i].field.lower())
        )
        non_fk_count = len(indices) - fk_count
        if non_fk_count > fk_count:  # Strictly >50% lack FK suffix
            for i in indices:
                if not _has_fk_suffix(deps[i].field.lower()):
                    penalize.add(i)

    if not penalize:
        return deps

    result: list[Dependency] = []
    for i, dep in enumerate(deps):
        if i in penalize:
            result.append(Dependency(
                **{**dep.__dict__,
                   "confidence": round(dep.confidence * _FAN_OUT_PENALTY, 3)},
            ))
        else:
            result.append(dep)
    return result


# ── Identifier reference validation ──────────────────────────────────

_IDENTIFIER_VALIDATION_PENALTY = 0.1

_GENERIC_IDENTIFIERS: frozenset[str] = frozenset({
    "id", "ids", "uuid", "pk", "key", "slug", "name",
})


def _strip_fk_suffix(name: str) -> str:
    """Strip common FK suffixes from a field name."""
    from idi.generation.dep_adapters.target_inference import _COMMON_FK_SUFFIXES
    lower = name.lower()
    for suffix in _COMMON_FK_SUFFIXES:
        stripped = lower.removesuffix(suffix)
        if stripped != lower and stripped:
            return stripped
    return lower


def apply_identifier_validation(
    deps: list[Dependency],
    identifier_index: dict[str, set[str]] | None,
) -> list[Dependency]:
    """Penalize body FK edges where field doesn't match target identifiers.

    For each body FK edge, checks if the field name (or its normalized form)
    matches any identifier the target resource produces. Conservative: passes
    edges when no identifier data is available for the target.
    """
    from idi.generation.dep_adapters.naming import stem_token

    if identifier_index is None:
        return deps

    result: list[Dependency] = []
    for dep in deps:
        if dep.source != "generic_odg:body":
            result.append(dep)
            continue

        field_lower = dep.field.lower()

        # Generic identifiers always pass.
        if field_lower in _GENERIC_IDENTIFIERS:
            result.append(dep)
            continue

        identifiers = identifier_index.get(dep.target_resource, set())

        # Conservative: empty identifier set -> pass.
        if not identifiers:
            result.append(dep)
            continue

        # Check multiple permutations for a match.
        matched = False

        # 1. Exact match.
        if field_lower in identifiers:
            matched = True

        # 2. Normalized match: strip FK suffixes and compare.
        if not matched:
            field_stripped = _strip_fk_suffix(field_lower)
            id_stripped = {_strip_fk_suffix(i) for i in identifiers}
            if field_stripped in id_stripped:
                matched = True

        # 3. Stemmed match: stem the stripped forms and compare.
        if not matched:
            field_stemmed = stem_token(field_stripped)
            id_stemmed = {stem_token(s) for s in id_stripped}
            if field_stemmed in id_stemmed:
                matched = True

        if matched:
            result.append(dep)
        else:
            result.append(Dependency(
                **{**dep.__dict__,
                   "confidence": round(dep.confidence * _IDENTIFIER_VALIDATION_PENALTY, 3)},
            ))
    return result


# ── Orchestrator ─────────────────────────────────────────────────────


def apply_gates(
    deps: list[Dependency],
    operation: OperationInfo,
    spec: dict[str, Any],
    skill_paths: dict[str, dict] | None = None,
    identifier_index: dict[str, set[str]] | None = None,
) -> list[Dependency]:
    """Apply all gates to a list of dependencies, returning survivors."""
    if not deps:
        return []

    survivors: list[Dependency] = []
    for dep in deps:
        field_schema = _resolve_field_schema(dep, operation, spec)
        killed = False
        for gate_fn in _GATES:
            result = gate_fn(dep, field_schema, spec, operation, skill_paths)
            if not result.keep:
                logger.debug(
                    "Gate %s killed edge %s:%s->%s: %s",
                    result.gate, operation.resource, dep.field,
                    dep.target_resource, result.reason,
                )
                killed = True
                break
        if not killed:
            survivors.append(dep)

    # Batch post-processing: fan-out suppression, then identifier validation.
    survivors = suppress_fan_out(survivors)
    survivors = apply_identifier_validation(survivors, identifier_index)

    return survivors
