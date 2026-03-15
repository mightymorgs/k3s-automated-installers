"""Stage 1 (partial): Load values.schema.json into SchemaInfo map.

Slice 1 scope: walk ``properties`` recursively, no ``$ref`` resolution.
$ref resolution is added in section-12 (Slice 2).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from idi.generation.helm.models import SchemaInfo

logger = logging.getLogger(__name__)

_UNSUPPORTED_KEYWORDS = frozenset({"if", "then", "else", "oneOf", "anyOf", "allOf", "additionalProperties"})


def load_schema(
    schema_path: str | Path | None,
) -> tuple[dict[tuple[str, ...], SchemaInfo], dict[str, Any]]:
    """Load values.schema.json and build SchemaInfo map.

    Args:
        schema_path: Path to values.schema.json, or None if not present.

    Returns:
        Tuple of (schema_overrides_map, diagnostics_dict).
        schema_overrides_map: keyed by tuple(path_segments) for unambiguous lookup.
        diagnostics_dict: {"ref_unresolved_count": int, "unsupported_keywords": list[str]}
    """
    diag: dict[str, Any] = {"ref_unresolved_count": 0, "unsupported_keywords": []}

    if schema_path is None:
        return {}, diag

    path = Path(schema_path)
    if not path.exists():
        return {}, diag

    try:
        raw = path.read_text(encoding="utf-8")
        schema = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Malformed JSON in schema file %s: %s", schema_path, exc)
        return {}, diag

    overrides: dict[tuple[str, ...], SchemaInfo] = {}
    _walk_schema(schema, (), overrides, diag)
    return overrides, diag


def _walk_schema(
    node: dict[str, Any],
    prefix: tuple[str, ...],
    overrides: dict[tuple[str, ...], SchemaInfo],
    diag: dict[str, Any],
) -> None:
    """Recursively walk a JSON Schema node, extracting SchemaInfo entries."""
    # Check for unsupported keywords at this level
    for kw in _UNSUPPORTED_KEYWORDS:
        if kw in node:
            if kw not in diag["unsupported_keywords"]:
                diag["unsupported_keywords"].append(kw)
            if kw in ("if", "then", "else"):
                logger.warning(
                    "Schema conditional '%s' at path %s — deferred to v2",
                    kw, ".".join(prefix) or "(root)",
                )

    properties = node.get("properties")
    if not isinstance(properties, dict):
        return

    required_list = node.get("required", [])
    if not isinstance(required_list, list):
        required_list = []

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        key = prefix + (prop_name,)

        # Handle $ref — log and skip (Slice 1)
        if "$ref" in prop_schema:
            ref_value = prop_schema["$ref"]
            logger.warning("Unresolved $ref: %s at %s", ref_value, ".".join(key))
            diag["ref_unresolved_count"] += 1
            continue

        # Check for unsupported keywords within property
        for kw in _UNSUPPORTED_KEYWORDS:
            if kw in prop_schema:
                if kw not in diag["unsupported_keywords"]:
                    diag["unsupported_keywords"].append(kw)

        prop_type = prop_schema.get("type")

        info = SchemaInfo(
            type=prop_type,
            format=prop_schema.get("format"),
            enum=prop_schema.get("enum"),
            required=prop_name in required_list,
            description=prop_schema.get("description"),
            default=prop_schema.get("default"),
            write_only=prop_schema.get("writeOnly", False),
            pattern=prop_schema.get("pattern"),
        )
        overrides[key] = info

        # Recurse into nested objects (but NOT arrays)
        if prop_type == "object" and "properties" in prop_schema:
            _walk_schema(prop_schema, key, overrides, diag)
