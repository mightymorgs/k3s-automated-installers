"""Stage 2: Recursive walk of values.yaml dict producing raw HelmFact objects.

Arrays are opaque leaves. Empty dicts are leaves. Scalars, null, and
arrays produce leaf facts. Non-empty dicts are recursed into.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from idi.generation.helm.models import HelmFact

logger = logging.getLogger(__name__)

_TRUNCATION_THRESHOLD = 4096  # bytes
_TRUNCATION_PREVIEW_LEN = 200


def get_json_type(value: Any) -> str:
    """Map Python type to JSON type string.

    CRITICAL: Check bool before int — bool is a subclass of int in Python.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def walk_values(values: dict[str, Any]) -> list[HelmFact]:
    """Recursively walk values.yaml dict and produce leaf HelmFact objects.

    Every non-empty dict is recursed into. Arrays, scalars, null, and empty
    dicts produce leaf facts. Path segments are stored raw (no escaping).
    """
    facts: list[HelmFact] = []
    _walk(values, [], facts)
    return facts


def _walk(
    node: dict[str, Any],
    prefix: list[str],
    facts: list[HelmFact],
) -> None:
    """Recursive walk helper."""
    for key, value in node.items():
        segments = prefix + [key]

        # Non-empty dict: recurse
        if isinstance(value, dict) and len(value) > 0:
            _walk(value, segments, facts)
            continue

        # Everything else is a leaf
        facts.append(_make_leaf(segments, value))


def _make_leaf(path_segments: list[str], value: Any) -> HelmFact:
    """Create a leaf HelmFact from path segments and value."""
    json_type = get_json_type(value)

    # Template detection
    has_template = isinstance(value, str) and "{{" in value

    # Default empty
    default_empty = value is None or value == ""

    # Format hint detection
    format_hint = _detect_format(path_segments, value)

    # Large value truncation
    default_truncated = False
    stored_value = value
    try:
        serialized = json.dumps(value, default=str)
        if len(serialized.encode("utf-8")) > _TRUNCATION_THRESHOLD:
            preview = serialized[:_TRUNCATION_PREVIEW_LEN]
            value_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
            stored_value = f"{preview}... [truncated, hash={value_hash}]"
            default_truncated = True
    except (TypeError, ValueError, OverflowError):
        pass

    return HelmFact(
        path=".".join(path_segments),
        path_segments=list(path_segments),
        uri="",
        default_value=stored_value,
        type=json_type,
        semantic_type=json_type,
        has_template=has_template,
        default_empty=default_empty,
        default_truncated=default_truncated,
        shape="config",
        format=format_hint,
        required=False,
        enum=None,
        description=None,
        is_toggle=False,
        conditional_on=None,
        feature=None,
        cross_app_signal=None,
        classifications=[],
        source="heuristic_default",
        confidence=0.50,
        needs_review=True,
    )


def _detect_format(path_segments: list[str], value: Any) -> str | None:
    """Detect format hints for multi-line string config blocks."""
    if not isinstance(value, str) or "\n" not in value:
        return None

    leaf_key = path_segments[-1].lower()
    if not leaf_key.endswith("config"):
        return None

    if "{" in value and "=" in value:
        return "hcl"
    if ":" in value:
        return "yaml"
    return None
