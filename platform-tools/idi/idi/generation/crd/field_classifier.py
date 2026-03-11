"""CRD field classifier — delegates to schema_walker + ref_detector pipeline.

Classifies CRD spec properties into roles:
- input_ref: consumer — needs an existing resource
- output_declaration: producer — operator creates this
- config_field: parameterization — no dep edges

The ClassifiedField dataclass is the canonical data model, imported
throughout the pipeline (output_writer.py, ref_detector.py, crd_dep.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.schema_walker import walk_crd_schema


@dataclass
class ClassifiedField:
    """A CRD field with its classified role."""

    field: str  # Dot-path: spec.issuerRef
    role: str  # input_ref | output_declaration | config_field
    confidence: float
    field_type: str  # string, object, array, etc.
    target_kind: str | None = None  # For input_ref: what it references
    target_group: str | None = None
    required: bool = False
    cross_namespace: bool = False
    description: str = ""
    detection_source: str = ""  # Identifies which classification layer produced this result
    fact_shape: str = ""        # "identity", "lifecycle", or "config"
    target_field: str = "name"  # canonical target field for URI fragment
    blocks_descendants: bool = False  # True = structural ref whose children are ref components


def classify_fields(
    spec_properties: dict[str, Any],
    spec_required: list[str],
    group: str,
    kind: str,
    registry: KindRegistry | None = None,
    prefix: str = "spec",
    current_service: str = "",
) -> list[ClassifiedField]:
    """Classify all spec properties into roles using the detection pipeline.

    Iterates walk_crd_schema results and delegates per-field classification
    to classify_walked_field from ref_detector. Applies parent-child
    deduplication to prevent the same reference from being classified twice.

    Args:
        spec_properties: The properties dict from spec.
        spec_required: Required field names.
        group: CRD API group.
        kind: CRD Kind name.
        registry: KindRegistry with core and CRD resources.
        prefix: Dot-path prefix (default: "spec").

    Returns:
        List of ClassifiedField with roles assigned.
    """
    # Lazy import to avoid circular dependency:
    # field_classifier -> ref_detector -> field_classifier (for ClassifiedField).
    from idi.generation.crd.ref_detector import classify_walked_field

    if registry is None:
        registry = KindRegistry()

    results: list[ClassifiedField] = []
    classified_blocking_ref_paths: set[str] = set()

    for field in walk_crd_schema(spec_properties, spec_required, prefix=prefix):
        # Parent-child deduplication: skip descendants of BLOCKING refs only.
        # Structural detectors (SKS, ref_tuple, structural_ref) set
        # blocks_descendants=True, meaning their children are ref components
        # (name, key, namespace) not independent references.
        if any(field.path.startswith(ref_path + ".") for ref_path in classified_blocking_ref_paths):
            continue

        # Get sibling fields for enum_kind detection and constraint_fk (C29).
        # Populate for: (a) string fields with enum values, or
        # (b) string fields with DNS-name patterns/formats (needed by C29).
        sibling_fields = None
        if field.schema.get("type") == "string" and (
            field.schema.get("enum")
            or field.schema.get("pattern")
            or field.schema.get("format")
        ):
            sibling_fields = _get_sibling_fields(
                spec_properties, field.parent_path, prefix,
            )

        classified_list = classify_walked_field(
            field, registry, kind, group,
            sibling_fields=sibling_fields,
            current_service=current_service,
        )

        for classified in classified_list:
            if classified.role == "input_ref" and classified.blocks_descendants:
                classified_blocking_ref_paths.add(field.path)

        results.extend(classified_list)

    return results


def _get_sibling_fields(
    root_properties: dict[str, Any],
    parent_path: str,
    prefix: str,
) -> dict[str, Any] | None:
    """Navigate to parent object's properties for sibling detection."""
    if parent_path == prefix:
        return root_properties

    # Walk the path segments to reach the parent.
    segments = parent_path[len(prefix) + 1:].split(".")
    current = root_properties
    for seg in segments:
        if not isinstance(current, dict):
            return None
        prop = current.get(seg, {})
        if not isinstance(prop, dict):
            return None
        # Handle arrays — dive into items.
        if prop.get("type") == "array":
            items = prop.get("items", {})
            if isinstance(items, dict) and "properties" in items:
                current = items["properties"]
            else:
                return None
        elif "properties" in prop:
            current = prop["properties"]
        else:
            return None
    return current
