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


# Precompiled regex for K8s apiVersion pattern.
_VERSION_RE = re.compile(r"^v\d+(?:(?:alpha|beta)\d+)?$")


def _parse_api_version(value: str) -> tuple[str, str] | None:
    """Parse a K8s apiVersion string into (group, version).

    Returns (group, version) or None if the string doesn't match
    any recognized apiVersion pattern.

    Examples:
        "apps/v1" -> ("apps", "v1")
        "cert-manager.io/v1" -> ("cert-manager.io", "v1")
        "v1" -> ("", "v1")  -- core API group
        "v1alpha1" -> ("", "v1alpha1")
        "not-valid" -> None
    """
    if not value:
        return None
    if "/" in value:
        idx = value.rfind("/")
        group = value[:idx]
        version = value[idx + 1:]
        if not group or not version or not _VERSION_RE.match(version):
            return None
        return (group, version)
    # No slash -- check if it's a bare version (core group).
    if _VERSION_RE.match(value):
        return ("", value)
    return None


def detect_ref_tuple(
    field: WalkedField,
    registry: KindRegistry,
) -> list[ClassifiedField]:
    """Detect structural reference tuple pattern (C19).

    Identifies object fields with {name, namespace?, kind?, apiGroup?, apiVersion?}
    as cross-resource references. Returns list of ClassifiedField with
    role="input_ref" and fact_shape="identity", or empty list if no Kind resolvable.
    """
    schema = field.schema

    # Step 1: Must be type: object with properties.
    if schema.get("type") != "object":
        return []
    properties = schema.get("properties")
    if not properties or not isinstance(properties, dict):
        return []

    # Step 2: Must have 'name' as a string property.
    name_prop = properties.get("name")
    if not name_prop or not isinstance(name_prop, dict):
        return []
    if name_prop.get("type") != "string":
        return []

    # Determine confidence based on whether name is required.
    required_fields = schema.get("required", [])
    confidence = 0.85 if "name" in required_fields else 0.75

    # Step 3: Must have at least one reference indicator.
    ref_indicators = {"namespace", "kind", "apiGroup", "apiVersion"}
    has_indicator = any(ind in properties for ind in ref_indicators)
    if not has_indicator:
        return []

    # Determine cross_namespace.
    cross_ns = "namespace" in properties

    # Step 4: Try kind enum resolution.
    kind_prop = properties.get("kind")
    if kind_prop and isinstance(kind_prop, dict):
        kind_enum = kind_prop.get("enum")
        if kind_enum and isinstance(kind_enum, list):
            results: list[ClassifiedField] = []
            all_kinds = registry.all_kinds()
            kind_lower_map = {k.lower(): k for k in all_kinds}
            for val in kind_enum:
                if not isinstance(val, str):
                    continue
                canonical = kind_lower_map.get(val.lower())
                if canonical:
                    target_group = registry.group_for_kind(canonical)
                    results.append(ClassifiedField(
                        field=field.path,
                        role="input_ref",
                        confidence=confidence,
                        field_type="object",
                        target_kind=canonical,
                        target_group=target_group,
                        required=field.required,
                        cross_namespace=cross_ns,
                        description=schema.get("description", ""),
                        detection_source="ref_detector:ref_tuple",
                        fact_shape="identity",
                        target_field="name",
                    ))
            if results:
                return results

    # Step 5: apiGroup/apiVersion fallback for Kind resolution.
    for api_key in ("apiGroup", "apiVersion"):
        api_prop = properties.get(api_key)
        if not api_prop or not isinstance(api_prop, dict):
            continue
        api_enum = api_prop.get("enum")
        if not api_enum or not isinstance(api_enum, list):
            continue
        for val in api_enum:
            if not isinstance(val, str):
                continue
            if api_key == "apiGroup":
                group_str = val
            else:
                parsed = _parse_api_version(val)
                if not parsed:
                    continue
                group_str = parsed[0]
            # Look up group in registry.
            kinds_in_group = registry.kinds_for_group(group_str)
            if len(kinds_in_group) == 1:
                target_kind = next(iter(kinds_in_group))
                target_group = group_str
                return [ClassifiedField(
                    field=field.path,
                    role="input_ref",
                    confidence=confidence,
                    field_type="object",
                    target_kind=target_kind,
                    target_group=target_group,
                    required=field.required,
                    cross_namespace=cross_ns,
                    description=schema.get("description", ""),
                    detection_source="ref_detector:ref_tuple",
                    fact_shape="identity",
                    target_field="name",
                )]

    # Step 6: Cannot resolve Kind -> return empty.
    return []


def _scan_for_kind_values(
    value: Any,
    depth: int = 0,
    max_depth: int = 3,
    _counter: list[int] | None = None,
    max_visited: int = 50,
) -> list[str]:
    """Recursively scan a value for 'kind' keys, returning found string values.

    Safety limits prevent resource exhaustion from pathological inputs.
    Does NOT mutate the input value.
    """
    if _counter is None:
        _counter = [0]

    if _counter[0] >= max_visited or depth > max_depth:
        return []

    _counter[0] += 1
    results: list[str] = []

    if isinstance(value, dict):
        for key, val in value.items():
            if key == "kind" and isinstance(val, str):
                results.append(val)
            elif isinstance(val, (dict, list)):
                results.extend(_scan_for_kind_values(
                    val, depth + 1, max_depth, _counter, max_visited,
                ))
    elif isinstance(value, list):
        for item in value:
            if _counter[0] >= max_visited:
                break
            results.extend(_scan_for_kind_values(
                item, depth + 1, max_depth, _counter, max_visited,
            ))

    return results


def detect_example_kinds(
    field: WalkedField,
    registry: KindRegistry,
) -> list[ClassifiedField]:
    """Detect Kind names in example/default values (C24).

    Scans example, default, and x-kubernetes-examples schema values
    for literal Kind names. Returns one ClassifiedField per matched Kind.
    """
    schema = field.schema
    all_kinds = registry.all_kinds()
    kind_lower_map = {k.lower(): k for k in all_kinds}

    # Collect all values to scan.
    values_to_scan: list[Any] = []
    for key in ("example", "default"):
        if key in schema:
            values_to_scan.append(schema[key])
    xke = schema.get("x-kubernetes-examples")
    if xke is not None:
        if isinstance(xke, list):
            values_to_scan.extend(xke)
        else:
            values_to_scan.append(xke)

    if not values_to_scan:
        return []

    # Scan for kind values.
    found_kinds: set[str] = set()
    for val in values_to_scan:
        # Check if the value itself is a string matching a Kind.
        if isinstance(val, str):
            canonical = kind_lower_map.get(val.lower())
            if canonical:
                found_kinds.add(canonical)
        # Recursive scan for kind keys.
        for kind_val in _scan_for_kind_values(val):
            canonical = kind_lower_map.get(kind_val.lower())
            if canonical:
                found_kinds.add(canonical)

    if not found_kinds:
        return []

    # Determine role based on status vs spec.
    is_status = field.parent_path.startswith("status")
    role = "output_declaration" if is_status else "input_ref"

    results: list[ClassifiedField] = []
    for kind_name in sorted(found_kinds):
        target_group = registry.group_for_kind(kind_name) or ""
        results.append(ClassifiedField(
            field=field.path,
            role=role,
            confidence=0.8,
            field_type=schema.get("type", "string"),
            target_kind=kind_name,
            target_group=target_group,
            required=field.required,
            description=schema.get("description", ""),
            detection_source="ref_detector:example_kind",
            fact_shape="identity",
            target_field="name",
        ))

    return results


def detect_apigroup_literal(
    field: WalkedField,
    registry: KindRegistry,
) -> list[ClassifiedField]:
    """Detect API group literals in enum constraints (C25).

    Finds API group strings (like apps/v1 or cert-manager.io/v1) in enum values.
    Only emits edges for unambiguous single-Kind groups. Multi-Kind groups
    produce no edges (precision > recall).
    """
    enum_values = field.schema.get("enum")
    if not enum_values or not isinstance(enum_values, list):
        return []

    results: list[ClassifiedField] = []
    seen_kinds: set[str] = set()

    for val in enum_values:
        if not isinstance(val, str):
            continue
        parsed = _parse_api_version(val)
        if parsed is None:
            continue
        group_str, _version = parsed

        # Look up group in registry.
        kinds_in_group = registry.kinds_for_group(group_str)
        if len(kinds_in_group) == 1:
            target_kind = next(iter(kinds_in_group))
            if target_kind in seen_kinds:
                continue
            seen_kinds.add(target_kind)
            results.append(ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=0.85,
                field_type=field.schema.get("type", "string"),
                target_kind=target_kind,
                target_group=group_str,
                required=field.required,
                description=field.schema.get("description", ""),
                detection_source="ref_detector:apigroup_literal",
                fact_shape="identity",
                target_field="name",
            ))

    return results


def detect_passthrough_manifest(
    field: WalkedField,
    registry: KindRegistry,
    manifest_flags: ManifestFlags | None = None,
) -> list[ClassifiedField]:
    """Detect pass-through manifest pattern (C26).

    Identifies CRD fields accepting raw K8s manifests via
    x-kubernetes-preserve-unknown-fields or x-kubernetes-embedded-resource.
    Mutates manifest_flags (if provided) when passthrough detected.
    Returns ClassifiedField list with role="input_ref" for constrained
    Kind enum edges, or empty list.
    """
    schema = field.schema

    # Step 1: Marker check -- must have one of the two K8s embedded markers.
    has_preserve = schema.get("x-kubernetes-preserve-unknown-fields") is True
    has_embedded = schema.get("x-kubernetes-embedded-resource") is True
    if not has_preserve and not has_embedded:
        return []

    # Step 2: apiVersion/kind presence check.
    properties = schema.get("properties", {})
    required_list = schema.get("required", [])
    has_av_kind_props = "apiVersion" in properties and "kind" in properties
    has_av_kind_required = "apiVersion" in required_list and "kind" in required_list
    if not has_av_kind_props and not has_av_kind_required:
        return []

    # Step 3: Set manifest flag.
    if manifest_flags is not None:
        manifest_flags.accepts_arbitrary_resources = True
        manifest_flags.passthrough_detection_source = "ref_detector:passthrough_manifest"
        manifest_flags.passthrough_field_path = field.path

    # Step 4: Check for constrained Kind edges.
    kind_prop = properties.get("kind")
    if not kind_prop or not isinstance(kind_prop, dict):
        return []
    kind_enum = kind_prop.get("enum")
    if not kind_enum or not isinstance(kind_enum, list):
        return []

    all_kinds = registry.all_kinds()
    kind_lower_map = {k.lower(): k for k in all_kinds}
    results: list[ClassifiedField] = []

    for val in kind_enum:
        if not isinstance(val, str):
            continue
        canonical = kind_lower_map.get(val.lower())
        if canonical:
            target_group = registry.group_for_kind(canonical)
            results.append(ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=0.95,
                field_type="object",
                target_kind=canonical,
                target_group=target_group,
                required=field.required,
                description=schema.get("description", ""),
                detection_source="ref_detector:passthrough_manifest",
                fact_shape="identity",
                target_field="name",
            ))

    return results


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

    # Priority 2: Reference tuple detection (C19).
    tuple_results = detect_ref_tuple(field, registry)
    if tuple_results:
        return tuple_results

    # --- Additive detectors (steps 3-6): results accumulate ---
    classifications: list[ClassifiedField] = []

    # Step 3: Enum Kind detection.
    enum_results = detect_enum_kind(field, registry, sibling_fields)
    classifications.extend(enum_results)

    # Step 4: Example/default Kind extraction (C24).
    example_results = detect_example_kinds(field, registry)
    classifications.extend(example_results)

    # Step 5: API group literal detection (C25).
    apigroup_results = detect_apigroup_literal(field, registry)
    classifications.extend(apigroup_results)

    # Step 6: Passthrough manifest detection (C26).
    passthrough_results = detect_passthrough_manifest(field, registry, manifest_flags)
    classifications.extend(passthrough_results)

    # If any additive detector fired, deduplicate and return.
    if classifications:
        return _deduplicate_classifications(classifications)

    # Side-effect NLP for *Name fields (non-dictionary).
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

    # Default — config_field.
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
