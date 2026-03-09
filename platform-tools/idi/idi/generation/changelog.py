"""Change detection, versioning, and idempotency analysis for skills.

Compares old and new skill data to compute semantic versions, content
hashes, and idempotency metadata.  All functions are pure (no shared
mutable state) or accept an explicit :class:`GeneratorContext`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from idi.generation.context import GeneratorContext


# ── Change detection ─────────────────────────────────────────────────


def detect_changes(
    current_fields: List[Dict[str, Any]],
    previous_fields: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Compare current and previous field lists, returning categorised changes.

    Analyses field-level differences and classifies them as:

    - **breaking**: removed required fields, changed field types,
      added required fields, optional-to-required transitions.
    - **features**: added optional fields.
    - **patches**: description updates, removed optional fields,
      required-to-optional transitions.

    Args:
        current_fields: Field dicts from the current skill version.
        previous_fields: Field dicts from the previous skill version.

    Returns:
        Dict with keys ``breaking``, ``features``, ``patches`` -- each a
        list of human-readable change description strings.
    """
    changes: Dict[str, List[str]] = {
        "breaking": [],
        "features": [],
        "patches": [],
    }

    current_by_name = {f["name"]: f for f in current_fields}
    previous_by_name = {f["name"]: f for f in previous_fields}

    # Removed fields
    for name, prev_field in previous_by_name.items():
        if name not in current_by_name:
            if prev_field.get("required"):
                changes["breaking"].append(f"Removed required field: {name}")
            else:
                changes["patches"].append(f"Removed optional field: {name}")

    # Added fields
    for name, curr_field in current_by_name.items():
        if name not in previous_by_name:
            if curr_field.get("required"):
                changes["breaking"].append(f"Added required field: {name}")
            else:
                changes["features"].append(f"Added optional field: {name}")

    # Modified fields (present in both versions)
    for name in current_by_name.keys() & previous_by_name.keys():
        curr = current_by_name[name]
        prev = previous_by_name[name]

        if curr.get("type") != prev.get("type"):
            changes["breaking"].append(
                f"Changed type of {name}: {prev.get('type')} -> {curr.get('type')}"
            )

        if curr.get("required") and not prev.get("required"):
            changes["breaking"].append(
                f"Field {name} changed from optional to required"
            )

        if prev.get("required") and not curr.get("required"):
            changes["patches"].append(
                f"Field {name} changed from required to optional"
            )

        if curr.get("description") != prev.get("description"):
            changes["patches"].append(f"Updated description for {name}")

    return changes


# ── Semantic versioning ──────────────────────────────────────────────


def compute_semantic_version(
    previous_version: Optional[str],
    changes: Dict[str, List[str]],
) -> str:
    """Compute a new semver string based on detected changes.

    Follows semantic versioning:

    - Breaking changes increment **MAJOR**, resetting minor and patch.
    - New features increment **MINOR**, resetting patch.
    - Patches increment **PATCH**.
    - No changes returns *previous_version* unchanged.

    Args:
        previous_version: Previous version string (e.g. ``"1.0.0"``),
            or ``None`` for brand-new skills.
        changes: Dict with ``breaking``, ``features``, ``patches`` lists
            as returned by :func:`detect_changes`.

    Returns:
        New version string.
    """
    if previous_version is None:
        return "1.0.0"

    try:
        parts = previous_version.split(".")
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return "1.0.0"

    if changes.get("breaking"):
        return f"{major + 1}.0.0"
    if changes.get("features"):
        return f"{major}.{minor + 1}.0"
    if changes.get("patches"):
        return f"{major}.{minor}.{patch + 1}"
    return previous_version


def compute_skill_version(
    current_metadata: Dict[str, Any],
    previous_metadata: Optional[Dict[str, Any]],
) -> Tuple[str, Dict[str, List[str]]]:
    """Full version computation: detect changes then compute semver.

    Compares ``required_fields``, ``optional_fields``, and
    ``response_key_fields`` between *current_metadata* and
    *previous_metadata* to detect breaking changes, new features,
    and patches.

    For JSON format, fields are stored as flat name lists rather
    than dicts with ``required`` flags.  This function synthesises
    field dicts from both formats for comparison.

    Args:
        current_metadata: Dict containing the current skill JSON data.
        previous_metadata: Dict containing the previous skill JSON data,
            or ``None`` for brand-new skills.

    Returns:
        Tuple of ``(new_version, changes_dict)``.
    """
    if previous_metadata is None:
        return "1.0.0", {}

    # Build field dicts from v2 flat-list format.
    current_fields = _fields_from_metadata(current_metadata)
    previous_fields = _fields_from_metadata(previous_metadata)

    # Detect changes in request fields (required + optional).
    changes = detect_changes(current_fields, previous_fields)

    # Also check response fields.
    current_resp = _response_fields_from_metadata(current_metadata)
    previous_resp = _response_fields_from_metadata(previous_metadata)
    response_changes = detect_changes(current_resp, previous_resp)

    for key in ("breaking", "features", "patches"):
        changes[key].extend(response_changes.get(key, []))

    new_version = compute_semantic_version(
        previous_metadata.get("version"),
        changes,
    )

    return new_version, changes


# ── Schema version extraction ────────────────────────────────────────


def get_schema_version(schema: Dict[str, Any]) -> str:
    """Extract version from an OpenAPI specification.

    Args:
        schema: Parsed OpenAPI spec dict.

    Returns:
        Version string from ``info.version``, or ``"unknown"`` if absent.
    """
    info = schema.get("info", {})
    return info.get("version", "unknown")


# ── Previous skill metadata ─────────────────────────────────────────


def get_previous_skill_metadata(skill_path: Path) -> Optional[Dict[str, Any]]:
    """Load previous skill metadata from disk for comparison.

    Reads JSON skill files.  Falls back to YAML-frontmatter parsing
    for legacy ``.md`` files.

    Args:
        skill_path: Path to the skill file (``.json`` or ``.md``).

    Returns:
        Parsed metadata dict, or ``None`` if the file does not exist
        or cannot be parsed.
    """
    if not skill_path.exists():
        return None

    try:
        content = skill_path.read_text(encoding="utf-8")

        # JSON format
        if skill_path.suffix == ".json":
            return json.loads(content)

        # Legacy v1 YAML-frontmatter format
        if content.startswith("---"):
            import yaml  # noqa: delayed import for optional dep

            parts = content.split("---", 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1])
    except Exception:
        pass

    return None


# ── Content hashing ──────────────────────────────────────────────────


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of a string, truncated to 12 hex characters.

    Args:
        content: Arbitrary string content.

    Returns:
        12-character lowercase hex digest.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


# ── Idempotency analysis ────────────────────────────────────────────


def determine_idempotency(
    method: str,
    operation: str,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Determine whether an HTTP operation is idempotent.

    HTTP method semantics:

    - **GET** / **PUT** / **DELETE**: inherently idempotent.
    - **PATCH**: typically idempotent (same patch applied twice = same result).
    - **POST**: usually *not* idempotent -- creates a new resource each time.

    For non-idempotent ``POST`` create operations, returns a ``check_with``
    stub (``{"pending": True}``) so the caller can fill it in once all
    sibling skills are known.

    Args:
        method: HTTP method (case-insensitive).
        operation: Logical operation type (e.g. ``"create"``, ``"list"``).

    Returns:
        Tuple of ``(is_idempotent, check_with_info)``.
    """
    method = method.upper()

    # Inherently idempotent methods
    if method in ("GET", "PUT", "DELETE", "PATCH"):
        return True, None

    # POST is usually not idempotent
    if method == "POST" and operation == "create":
        return False, {"pending": True}

    return True, None


# ── Check-skill lookup ───────────────────────────────────────────────


def find_check_skill(
    ctx: GeneratorContext,
    service: str,
    resource: str,
) -> Optional[Dict[str, str]]:
    """Find a list skill that can verify resource existence.

    Searches ``ctx.generated_skill_paths`` for a ``list`` operation
    on the same service/resource.  Used to populate ``check_with``
    for non-idempotent create operations.

    Args:
        ctx: Generator context with ``generated_skill_paths`` populated.
        service: Service name (e.g. ``"authentik"``).
        resource: Resource name (e.g. ``"oauth2"``).

    Returns:
        Dict with ``skill`` (path) and ``match_field`` keys, or ``None``
        if no list skill exists.
    """
    list_path = f"{service}/{resource}/list"

    if list_path in ctx.generated_skill_paths:
        return {
            "skill": list_path,
            "match_field": "name",
        }

    return None


# ── Existence-check extraction ───────────────────────────────────────


def extract_existence_check(
    ctx: GeneratorContext,
    service: str,
    resource: str,
    method: str,
    path: str,
) -> Optional[Dict[str, Any]]:
    """Extract existence-check metadata for non-idempotent create operations.

    For a ``POST`` (create) operation, locates the corresponding ``GET``
    (list) endpoint on the same resource and documents how an LLM can
    check whether the resource already exists before creating it.

    This is complementary to ``check_with`` (which tells the LLM *that*
    it should check) -- this tells it *how*.

    Uses ``_same_resource`` internally, which requires a
    ``build_resource_name`` callable on ``ctx`` (set up by the resource
    namer module).  If no list endpoint is found, returns ``None``.

    Args:
        ctx: Generator context with ``schema`` populated.
        service: Service name.
        resource: Resource name (sanitised, possibly compound).
        method: HTTP method of the create operation.
        path: API path of the create operation.

    Returns:
        Dict with ``endpoint``, ``method``, ``query_param``,
        ``match_field``, ``match_type``, ``count_field``, and
        ``result_wrapper`` keys, or ``None`` if no list endpoint found.
    """
    paths = ctx.schema.get("paths", {})

    list_path = None
    list_op = None

    # Find matching GET (list) endpoint for the same resource.
    for p, methods in paths.items():
        if "get" not in methods:
            continue
        if not _same_resource(ctx, p, resource):
            continue
        # Prefer collection endpoints (no trailing {id} parameter).
        if not p.rstrip("/").endswith("}"):
            list_path = p
            list_op = methods["get"]

    if not list_path or not list_op:
        return None

    # Extract query parameters for filtering.
    query_params: List[Dict[str, str]] = []
    for param in list_op.get("parameters", []):
        if param.get("in") == "query":
            query_params.append({
                "name": param["name"],
                "type": param.get("schema", {}).get("type", "string"),
            })

    # Identify the search/filter parameter.
    search_param: Optional[str] = None
    for p in query_params:
        if p["name"] in ("search", "name", "filter", "q", "query"):
            search_param = p["name"]
            break

    # Analyse response schema for list endpoint.
    responses = list_op.get("responses", {})
    list_response = responses.get("200", responses.get(200, {}))
    list_schema = (
        list_response
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )

    props = list_schema.get("properties", {})

    # Detect response wrapper field.
    response_wrapper: Optional[str] = None
    for wrapper_name in ("results", "data", "items", "content", "records"):
        if wrapper_name in props:
            response_wrapper = wrapper_name
            break

    # Detect count/total field.
    count_field: Optional[str] = None
    for count_name in ("count", "total", "total_count", "pagination"):
        if count_name in props:
            if count_name == "pagination":
                pag_schema = props[count_name]
                if (
                    "properties" in pag_schema
                    and "count" in pag_schema["properties"]
                ):
                    count_field = "pagination.count"
            else:
                count_field = count_name
            break

    # meta.total pattern
    if not count_field and "meta" in props:
        meta_schema = props["meta"]
        if (
            "properties" in meta_schema
            and "total" in meta_schema["properties"]
        ):
            count_field = "meta.total"

    return {
        "endpoint": list_path,
        "method": "GET",
        "query_param": search_param,
        "match_field": "name",
        "match_type": "exact",
        "count_field": count_field,
        "result_wrapper": response_wrapper,
    }


# ── Internal helpers ─────────────────────────────────────────────────


def _fields_from_metadata(
    metadata: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Synthesise field dicts from JSON flat-list format.

    Converts ``required_fields`` and ``optional_fields`` lists into
    the ``[{"name": ..., "required": bool}]`` shape expected by
    :func:`detect_changes`.
    """
    fields: List[Dict[str, Any]] = []
    for name in metadata.get("required_fields", []):
        fields.append({"name": name, "required": True})
    for name in metadata.get("optional_fields", []):
        fields.append({"name": name, "required": False})
    return fields


def _response_fields_from_metadata(
    metadata: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Synthesise field dicts from ``response_key_fields``."""
    return [
        {"name": name, "required": False}
        for name in metadata.get("response_key_fields", [])
    ]


def _same_resource(
    ctx: GeneratorContext,
    path: str,
    resource: str,
) -> bool:
    """Check whether an API *path* corresponds to *resource*.

    Delegates to the resource namer's ``build_resource_name`` if
    available on the context's adapter.  Falls back to a simple
    last-segment comparison.

    Args:
        ctx: Generator context.
        path: API path to check.
        resource: Target resource name (sanitised, possibly compound).

    Returns:
        ``True`` if *path* is for the same resource.
    """
    # If the adapter provides build_resource_name, use it.
    if hasattr(ctx.adapter, "build_resource_name"):
        path_resource = ctx.adapter.build_resource_name(path)
        return path_resource == resource

    # Fallback: simple last-segment comparison.
    parts = path.strip("/").split("/")
    non_param = [p for p in parts if p and not p.startswith("{")]
    if not non_param:
        return False
    from idi.generation.utils import sanitize_name

    return sanitize_name(non_param[-1]) == resource


