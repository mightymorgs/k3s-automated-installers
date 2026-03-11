"""Generic response envelope detector.

Identifies and unwraps 4 common response wrapper patterns, checked in
priority order (first match wins):

1. HAL ``_embedded`` — confidence 0.95
2. Pagination wrapper — confidence 0.9
3. Single-field wrapper — confidence 0.9 (with metadata) or 0.7 (without)
4. Externally tagged — confidence 0.95

Callers should only act on results with ``confidence >= 0.8``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Array property names that indicate the "data" portion of a pagination envelope
# Ordered tuple: first match wins when multiple data-named arrays exist
DATA_FIELD_NAMES_ORDERED = ("data", "items", "results", "records", "entries")
DATA_FIELD_NAMES = frozenset(DATA_FIELD_NAMES_ORDERED)

# Sibling property names that indicate pagination metadata
PAGINATION_INDICATORS = frozenset({
    "count", "total", "total_count", "page", "per_page", "offset", "limit",
    "cursor", "has_more", "has_next", "next", "previous", "prev",
    "links", "meta", "result_info", "page_info", "pagination",
})

# Property names that indicate a single-field wrapper
WRAPPER_FIELD_NAMES = frozenset({"data", "result", "response", "payload", "body", "content"})

# Sibling property names that indicate metadata alongside a wrapper field
METADATA_FIELD_NAMES = frozenset({
    "errors", "success", "message", "meta", "status", "code",
    "messages", "result_info", "error",
})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnvelopeResult:
    """Detection result for a response envelope pattern."""

    unwrap_path: str   # Dot-separated path to actual data (e.g., "_embedded.users")
    pattern: str       # One of: 'hal_embedded', 'pagination', 'single_field', 'externally_tagged'
    confidence: float  # Pattern-specific confidence score (0.7 - 0.95)


# ---------------------------------------------------------------------------
# Type guard
# ---------------------------------------------------------------------------

def _is_object_or_object_array(schema: dict[str, Any]) -> bool:
    """Check if a schema represents an Object or Array of Objects.

    Primitives and arrays of primitives are NOT envelopes.
    """
    if not isinstance(schema, dict):
        return False

    schema_type = schema.get("type", "")

    # Direct object
    if schema_type == "object" and "properties" in schema:
        return True

    # Array of objects
    if schema_type == "array":
        items = schema.get("items", {})
        if isinstance(items, dict):
            return items.get("type") == "object" or "properties" in items
        return False

    # No explicit type but has properties → infer object
    if "properties" in schema:
        return True

    return False


# ---------------------------------------------------------------------------
# Pattern detectors
# ---------------------------------------------------------------------------

def _detect_hal_embedded(properties: dict[str, Any]) -> EnvelopeResult | None:
    """Pattern 1: HAL _embedded (confidence 0.95)."""
    embedded = properties.get("_embedded")
    if not isinstance(embedded, dict):
        return None

    # Accept explicit type: "object" or implicit (has properties)
    if embedded.get("type") not in ("object", None) and "properties" not in embedded:
        return None

    sub_props = embedded.get("properties", {})
    if not sub_props:
        return None

    # HAL typically has exactly one sub-property under _embedded
    if len(sub_props) == 1:
        resource_name = next(iter(sub_props))
        return EnvelopeResult(
            unwrap_path=f"_embedded.{resource_name}",
            pattern="hal_embedded",
            confidence=0.95,
        )

    return None


def _detect_pagination(
    properties: dict[str, Any],
    path: str | None = None,
) -> EnvelopeResult | None:
    """Pattern 2: Pagination wrapper (confidence 0.9)."""
    prop_names = set(properties.keys())

    # Must have at least one pagination indicator as sibling
    if not prop_names & PAGINATION_INDICATORS:
        return None

    # Build candidate names: standard data names + resource name from path
    candidates = list(DATA_FIELD_NAMES_ORDERED)
    if path:
        segments = [s for s in path.split("/") if s and not s.startswith("{")]
        if segments:
            candidates.append(segments[-1].lower())

    # Find array properties with data-naming convention (ordered: first match wins)
    for name in candidates:
        prop = properties.get(name)
        if not isinstance(prop, dict) or prop.get("type") != "array":
            continue
        # Type guard: only arrays of objects, not primitive arrays
        if not _is_object_or_object_array(prop):
            continue
        return EnvelopeResult(
            unwrap_path=name,
            pattern="pagination",
            confidence=0.9,
        )

    return None


def _detect_single_field(properties: dict[str, Any]) -> EnvelopeResult | None:
    """Pattern 3: Single-field wrapper (confidence 0.9 or 0.7)."""
    prop_names = set(properties.keys())

    # Exactly one wrapper-named property required (precision guard)
    wrapper_candidates = prop_names & WRAPPER_FIELD_NAMES
    if len(wrapper_candidates) != 1:
        return None

    # Check the single candidate
    for field_name in wrapper_candidates:
        inner_schema = properties[field_name]
        if not isinstance(inner_schema, dict):
            continue

        # Type guard: only object or array-of-objects
        if not _is_object_or_object_array(inner_schema):
            continue

        # Check for metadata siblings
        has_metadata = bool(prop_names & METADATA_FIELD_NAMES)
        confidence = 0.9 if has_metadata else 0.7

        return EnvelopeResult(
            unwrap_path=field_name,
            pattern="single_field",
            confidence=confidence,
        )

    return None


def _detect_externally_tagged(
    properties: dict[str, Any],
    path: str | None,
) -> EnvelopeResult | None:
    """Pattern 4: Externally tagged (confidence 0.95)."""
    if not path:
        return None

    # Must have exactly one property
    if len(properties) != 1:
        return None

    # Extract last non-parameter path segment
    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    if not segments:
        return None
    last_segment = segments[-1].lower()

    # Check if the single property name matches
    prop_name = next(iter(properties))
    if prop_name.lower() != last_segment:
        return None

    # Type guard
    inner_schema = properties[prop_name]
    if not isinstance(inner_schema, dict) or not _is_object_or_object_array(inner_schema):
        return None

    return EnvelopeResult(
        unwrap_path=prop_name,
        pattern="externally_tagged",
        confidence=0.95,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_envelope(
    response_schema: dict[str, Any],
    path: str | None = None,
) -> EnvelopeResult | None:
    """Detect response envelope pattern and return unwrap instructions.

    Checks 4 patterns in priority order: HAL _embedded, pagination wrapper,
    single-field wrapper, externally tagged. Returns the first match, or
    None if no pattern is detected.

    Args:
        response_schema: The response schema dict with 'properties' at top level.
        path: The API path (needed for externally-tagged pattern matching).

    Returns:
        EnvelopeResult with unwrap_path, pattern name, and confidence score,
        or None if no envelope pattern is detected.
    """
    if not isinstance(response_schema, dict):
        return None

    properties = response_schema.get("properties")
    if not properties or not isinstance(properties, dict):
        return None

    # Check patterns in priority order (first match wins)
    result = _detect_hal_embedded(properties)
    if result:
        return result

    result = _detect_pagination(properties, path)
    if result:
        return result

    result = _detect_single_field(properties)
    if result:
        return result

    result = _detect_externally_tagged(properties, path)
    if result:
        return result

    return None


def navigate_unwrap_path(schema: dict[str, Any], unwrap_path: str) -> dict[str, Any] | None:
    """Navigate into a schema following a dot-separated unwrap path.

    Args:
        schema: Response schema with 'properties'.
        unwrap_path: Dot-separated path like '_embedded.users'.

    Returns:
        The inner schema at the unwrap path, or None if navigation fails.
    """
    current = schema
    for segment in unwrap_path.split("."):
        props = current.get("properties", {})
        if segment not in props:
            return None
        current = props[segment]
        if not isinstance(current, dict):
            return None
    return current
