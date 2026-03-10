"""Multi-strategy ref/output detection for CRD schemas.

Given a WalkedField from the schema walker, classifies it using multiple
detection strategies. Each strategy is an independent, testable function.
A top-level orchestrator runs them in priority order.

C10: status field output detection
C15: absorbs detection logic from kubernetes_crd.py
C18: enum Kind detection
C19: reference tuple detection (Phase 3)
C24: examples/defaults extraction (Phase 3)
C25: API group literals in constraints (Phase 3)
C26: pass-through manifest detection (Phase 3)
C27: status addressability upgrade (Phase 3)
C28: false-positive suppression (Phase 3)

Critical: Precision > recall. No edge emitted below confidence 0.7.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.schema_walker import WalkedField
from idi.generation.crd.side_effect_registry import (
    classify_name_field,
    get_side_effects,
)


@dataclass
class ManifestFlags:
    """Manifest-level flags detected during field classification.

    Pass-in accumulator: caller creates one instance before the walker
    loop, passes it to classify_walked_field, detectors mutate it.
    """

    accepts_arbitrary_resources: bool = False
    passthrough_detection_source: str = ""
    passthrough_field_path: str = ""  # For debugging: which field triggered the flag

# Constants moved from adapters/kubernetes_crd.py.
OBJECT_REFERENCE_PATTERNS = [
    "io.k8s.api.core.v1.ObjectReference",
    "ObjectReference",
]

LABEL_SELECTOR_PATTERNS = [
    "io.k8s.apimachinery.pkg.apis.meta.v1.LabelSelector",
    "LabelSelector",
]

# Precompiled regex for stripping Ref suffix.
_REF_SUFFIX_RE = re.compile(r"[Rr]efs?$")

# Precompiled regex for Kind-in-field-name detection (status outputs).
# Matches camelCase boundary before a Kind name: lowercase char -> uppercase char.
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z])([A-Z])")


def detect_ref(
    field: WalkedField,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Detect input references in a walked field.

    Checks in strict order — exclusions first, then positive detectors:
    1. LabelSelector exclusion
    2. ObjectReference exclusion
    3. KindRegistry name match
    4. Structural ref (object + name + Ref suffix + KindRegistry prefix)
    5. Array ref (C7)
    """
    schema = field.schema
    ref_value = schema.get("$ref", "")

    # Step 1: LabelSelector exclusion.
    if ref_value:
        for pattern in LABEL_SELECTOR_PATTERNS:
            if pattern in ref_value:
                return None

    # Step 2: ObjectReference exclusion.
    if ref_value:
        for pattern in OBJECT_REFERENCE_PATTERNS:
            if pattern in ref_value:
                return None

    # Step 3: KindRegistry name match.
    is_ref, target_kind, target_plural, target_group = registry.is_ref_field(
        field.name,
    )
    if is_ref and target_kind:
        cross_ns = detect_namespace(field)
        return ClassifiedField(
            field=field.path,
            role="input_ref",
            confidence=0.9,
            field_type=schema.get("type", "string"),
            target_kind=target_kind,
            target_group=target_group,
            required=field.required,
            cross_namespace=cross_ns,
            description=schema.get("description", ""),
            detection_source="ref_detector:kind_registry",
            fact_shape="identity",
            target_field="name",
        )

    # Step 4: Structural ref.
    lower_name = field.name.lower()
    if (
        schema.get("type") == "object"
        and "name" in schema.get("properties", {})
        and lower_name.endswith("ref")
    ):
        # Extract prefix by stripping Ref suffix, capitalize first letter.
        base = re.sub(r"[Rr]ef$", "", field.name)
        if base:
            inferred_kind = base[0].upper() + base[1:] if base else ""
            # Check if KindRegistry recognizes this Kind.
            if inferred_kind and inferred_kind in registry.all_kinds():
                cross_ns = detect_namespace(field)
                group = registry.group_for_kind(inferred_kind)
                return ClassifiedField(
                    field=field.path,
                    role="input_ref",
                    confidence=0.9,
                    field_type="object",
                    target_kind=inferred_kind,
                    target_group=group,
                    required=field.required,
                    cross_namespace=cross_ns,
                    description=schema.get("description", ""),
                    detection_source="ref_detector:structural_ref",
                    fact_shape="identity",
                    target_field="name",
                )

    # Step 5: Array ref (C7).
    if schema.get("type") == "array" and (
        lower_name.endswith("refs") or lower_name.endswith("ref")
    ):
        # Strip plural 's' and 'Ref' suffix to get base Kind name.
        base = _REF_SUFFIX_RE.sub("", field.name)
        if base:
            inferred_kind = base[0].upper() + base[1:] if base else ""
            if inferred_kind and inferred_kind in registry.all_kinds():
                group = registry.group_for_kind(inferred_kind)
                return ClassifiedField(
                    field=field.path,
                    role="input_ref",
                    confidence=0.85,
                    field_type="array",
                    target_kind=inferred_kind,
                    target_group=group,
                    required=field.required,
                    description=schema.get("description", ""),
                    detection_source="ref_detector:array_ref",
                    fact_shape="identity",
                    target_field="name",
                )

    return None


def detect_enum_kind(
    field: WalkedField,
    registry: KindRegistry,
    sibling_fields: dict[str, Any] | None = None,
) -> list[ClassifiedField]:
    """Detect enum values matching known Kinds (C18).

    The enum field is a discriminator, not a ref. When a sibling 'name'
    field exists, the ref points to the sibling, not the enum.

    Args:
        field: The walked field (expected to have an 'enum' in schema).
        registry: KindRegistry for Kind lookup.
        sibling_fields: The parent object's properties dict, if available.

    Returns:
        List of ClassifiedField for each matched Kind.
    """
    enum_values = field.schema.get("enum")
    if not enum_values or not isinstance(enum_values, list):
        return []

    # Build case-insensitive lookup from registry.
    all_kinds = registry.all_kinds()
    kind_lower_map: dict[str, str] = {k.lower(): k for k in all_kinds}

    matched_kinds: list[str] = []
    for val in enum_values:
        if not isinstance(val, str):
            continue
        canonical = kind_lower_map.get(val.lower())
        if canonical:
            matched_kinds.append(canonical)

    if not matched_kinds:
        return []

    results: list[ClassifiedField] = []
    has_sibling_name = sibling_fields is not None and "name" in sibling_fields

    for kind_name in matched_kinds:
        group = registry.group_for_kind(kind_name)
        if has_sibling_name:
            # Point to sibling name field path.
            # Replace the enum field's leaf name with "name" in the path.
            parts = field.path.rsplit(".", 1)
            sibling_path = f"{parts[0]}.name" if len(parts) > 1 else "name"
            results.append(ClassifiedField(
                field=sibling_path,
                role="input_ref",
                confidence=0.95,
                field_type="string",
                target_kind=kind_name,
                target_group=group,
                required=field.required,
                description="",
                detection_source="ref_detector:enum_kind",
                fact_shape="identity",
                target_field="name",
            ))
        else:
            # No sibling name — point to enum field itself.
            results.append(ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=0.8,
                field_type=field.schema.get("type", "string"),
                target_kind=kind_name,
                target_group=group,
                required=field.required,
                description=field.schema.get("description", ""),
                detection_source="ref_detector:enum_kind",
                fact_shape="identity",
                target_field="name",
            ))

    return results


def detect_status_output(
    field: WalkedField,
    kind: str,
    group: str,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Classify status fields as output_declarations (C10).

    Three tiers:
    1. Kind in field name — confidence 0.85, fact_shape="identity"
    2. Conditions pattern — confidence 0.9, fact_shape="lifecycle"
    3. Generic status field — confidence 0.6 (BELOW 0.7 threshold)
    """
    schema = field.schema
    field_type = schema.get("type", "string")

    # Tier 2: Conditions pattern (check first — it's the most specific).
    if field.name == "conditions" and field_type == "array":
        return ClassifiedField(
            field=field.path,
            role="output_declaration",
            confidence=0.9,
            field_type=field_type,
            target_kind=kind,
            target_group=group,
            detection_source="ref_detector:status_output",
            fact_shape="lifecycle",
            target_field="type",
        )

    # Tier 1: Kind in field name.
    # Split the field name on camelCase boundaries and check if any
    # subsequence matches a known Kind.
    all_kinds = registry.all_kinds()
    for known_kind in all_kinds:
        if known_kind.lower() in field.name.lower():
            return ClassifiedField(
                field=field.path,
                role="output_declaration",
                confidence=0.85,
                field_type=field_type,
                target_kind=known_kind,
                target_group=registry.group_for_kind(known_kind),
                detection_source="ref_detector:status_output",
                fact_shape="identity",
                target_field="name",
            )

    # Tier 3: Generic status field — below emission threshold.
    return ClassifiedField(
        field=field.path,
        role="output_declaration",
        confidence=0.6,
        field_type=field_type,
        target_kind=kind,
        target_group=group,
        detection_source="ref_detector:status_output",
        fact_shape="config",
        target_field=field.name,
    )


def detect_namespace(field: WalkedField) -> bool:
    """Check if a field's schema indicates cross-namespace reference.

    Returns True if the field is an object with a 'namespace' property.
    """
    schema = field.schema
    if schema.get("type") != "object":
        return False
    return "namespace" in schema.get("properties", {})


def _deduplicate_classifications(
    classifications: list[ClassifiedField],
) -> list[ClassifiedField]:
    """Deduplicate classifications by (field, role, target_kind, target_group).

    When duplicates exist, keep the one with highest confidence.
    """
    if not classifications:
        return classifications

    best: dict[tuple[str, str, str | None, str | None], ClassifiedField] = {}
    for c in classifications:
        key = (c.field, c.role, c.target_kind, c.target_group)
        existing = best.get(key)
        if existing is None or c.confidence > existing.confidence:
            best[key] = c
    return list(best.values())


def classify_walked_field(
    field: WalkedField,
    registry: KindRegistry,
    kind: str,
    group: str,
    sibling_fields: dict[str, Any] | None = None,
    manifest_flags: ManifestFlags | None = None,
) -> list[ClassifiedField]:
    """Top-level orchestrator for spec field classification.

    Runs detectors in priority order:
    1. detect_ref — structural/KindRegistry/array ref detection
    2. detect_enum_kind — enum values matching known Kinds
    3. Side-effect registry NLP — for *Name fields
    4. Default — config_field

    Note: detect_status_output is NOT called here — it is invoked
    separately on status fields by callers.

    Args:
        field: WalkedField from schema walker.
        registry: KindRegistry instance.
        kind: The source CRD's Kind name.
        group: The source CRD's API group.
        sibling_fields: Parent object's properties (for enum_kind).
        manifest_flags: Optional accumulator for manifest-level flags.
            If provided, passthrough detection will mutate it.
            If None, passthrough detection still runs but the flag is lost.

    Returns:
        List of ClassifiedField (usually 1 item; multiple for enum_kind).
    """
    # Priority 0: Side-effect dictionary for *Name fields.
    # The side-effect dictionary (confidence 0.95) has domain-specific knowledge
    # that overrides structural detection (0.9). For example, Certificate's
    # spec.secretName is an output_declaration (operator creates the Secret),
    # but KindRegistry would classify it as input_ref (Secret+Name pattern).
    # Dictionary knowledge MUST win.
    lower_name = field.name.lower()
    if lower_name.endswith("name") and field.schema.get("type") == "string":
        effects = get_side_effects(group, kind)
        for eff in effects:
            if eff["field"] == field.path:
                return [ClassifiedField(
                    field=field.path,
                    role="output_declaration",
                    confidence=0.95,
                    field_type=field.schema.get("type", "string"),
                    target_kind=eff["produces_kind"],
                    target_group=eff["produces_group"],
                    required=field.required,
                    description=field.schema.get("description", ""),
                    detection_source="side_effect:operator_dict",
                    fact_shape="identity",
                )]

    # Priority 1: Structural ref detection.
    ref_result = detect_ref(field, registry)
    if ref_result is not None:
        return [ref_result]

    # Priority 2: Enum Kind detection.
    enum_results = detect_enum_kind(field, registry, sibling_fields)
    if enum_results:
        return enum_results

    # Priority 3: Side-effect NLP for *Name fields (non-dictionary).
    if lower_name.endswith("name") and field.schema.get("type") == "string":
        role, confidence = classify_name_field(
            field.path, group, kind, field.schema.get("description", ""),
        )
        if role == "output_declaration":
            return [ClassifiedField(
                field=field.path,
                role="output_declaration",
                confidence=confidence,
                field_type=field.schema.get("type", "string"),
                required=field.required,
                description=field.schema.get("description", ""),
                detection_source="side_effect:nlp_output",
                fact_shape="identity",
            )]
        if role == "input_ref":
            # Try KindRegistry for target resolution.
            is_ref, target_kind, target_plural, target_group = registry.is_ref_field(
                field.name, current_group=group,
            )
            return [ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=confidence,
                field_type=field.schema.get("type", "string"),
                target_kind=target_kind,
                target_group=target_group,
                required=field.required,
                description=field.schema.get("description", ""),
                detection_source="side_effect:nlp_input",
                fact_shape="identity" if target_kind else "config",
            )]

    # Priority 4: Default — config_field.
    return [ClassifiedField(
        field=field.path,
        role="config_field",
        confidence=0.5,
        field_type=field.schema.get("type", "string"),
        required=field.required,
        description=field.schema.get("description", ""),
        detection_source="default:config_field",
        fact_shape="config",
        target_field=field.name,
    )]
