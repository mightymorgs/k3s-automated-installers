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
C20: scale subresource analysis (Phase 5A)
C21: webhook configuration parsing (Phase 5A — in rbac_deps.py)
C22: embedded workload shape matching (Phase 5A)
C29: constraint-based FK inference (Phase 5A)
C30: cross-CRD reference shape mining (Phase 5A)
C32: x-kubernetes extension fingerprinting (Phase 5A)
SecretKeySelector shape detection (Remediation)
Parent-name → Kind resolution / C12 port (Remediation)
readOnly → output classification (Remediation)

Critical: Precision > recall. No edge emitted below confidence 0.7.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
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

# ---------------------------------------------------------------------------
# Phase 5A: Data types and constants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkloadFingerprint:
    """Structural fingerprint for a well-known K8s type."""

    required_properties: frozenset[str]
    container_shape: frozenset[str]  # properties expected in container array items
    optional_properties: frozenset[str]
    min_match_count: int  # required + minimum optional matches needed
    produces_kind: str


WORKLOAD_SHAPES: dict[str, WorkloadFingerprint] = {
    "PodTemplateSpec": WorkloadFingerprint(
        required_properties=frozenset({"containers"}),
        container_shape=frozenset({"image", "name"}),
        optional_properties=frozenset({
            "initContainers", "volumes", "serviceAccountName",
            "nodeSelector", "tolerations", "affinity",
        }),
        min_match_count=2,
        produces_kind="Pod",
    ),
    "JobSpec": WorkloadFingerprint(
        required_properties=frozenset({"template"}),
        container_shape=frozenset(),
        optional_properties=frozenset({
            "backoffLimit", "completions", "parallelism",
            "activeDeadlineSeconds", "ttlSecondsAfterFinished",
        }),
        min_match_count=2,
        produces_kind="Job",
    ),
    "ServiceSpec": WorkloadFingerprint(
        required_properties=frozenset({"ports"}),
        container_shape=frozenset(),
        optional_properties=frozenset({
            "selector", "clusterIP", "type",
            "externalTrafficPolicy", "sessionAffinity", "loadBalancerIP",
        }),
        min_match_count=2,
        produces_kind="Service",
    ),
}

K8S_NAME_PATTERNS: list[str] = [
    r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$",                                      # RFC 1123 label
    r"^[a-z]([a-z0-9\-]*[a-z0-9])?$",                                          # RFC 1035 label
    r"^[a-z0-9]([a-z0-9\-\.]*[a-z0-9])?$",                                     # subdomain name
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$",    # FQDN
]

K8S_FORMAT_ALLOWLIST: frozenset[str] = frozenset({
    "dns1123-label",
    "dns1123-subdomain",
    "hostname",
    "qualified-name",
})

# Field names that appear in K8s inline objects (containers, volumes, etc.).
# Co-occurrence of >= 3 with a 'name' field inside an array signals a
# list-map merge key, not a cross-resource reference.
_INLINE_OBJECT_SIBLINGS: frozenset[str] = frozenset({
    "image", "command", "args", "env", "ports",
    "volumeMounts", "resources", "mountPath",
    "containerPort", "protocol", "readOnly", "subPath",
})


def is_inline_object_name(field: WalkedField) -> bool:
    """Check if a 'name' field is a list-map key in an inline K8s object.

    Returns True when the field is inside an array (is_array_item) and
    has >= 3 siblings matching well-known container/volume spec fields.
    """
    if not field.is_array_item:
        return False
    overlap = field.sibling_names & _INLINE_OBJECT_SIBLINGS
    return len(overlap) >= 3


@dataclass(frozen=True)
class CatalogEntry:
    """A confirmed reference shape from cross-CRD analysis."""

    fingerprint: str
    target_kind: str
    confirmed_in: tuple[str, ...]  # CRD Kinds that confirmed this shape
    confidence: float
    required_properties: frozenset[str]


@dataclass
class ShapeCatalog:
    """Pre-computed shape catalog for cross-CRD reference matching."""

    shapes: dict[str, CatalogEntry]  # fingerprint -> entry

    @classmethod
    def load(cls, path: str | None = None) -> ShapeCatalog:
        """Load catalog from disk. Returns empty catalog if file missing.

        Path resolution: if no path given, resolve relative to project root
        (platform-tools/idi/../../catalog/shape_catalog.json).
        """
        if path is None:
            project_root = Path(__file__).parent.parent.parent.parent.parent
            path = str(project_root / "catalog" / "shape_catalog.json")

        catalog_path = Path(path)
        if not catalog_path.is_file():
            return cls(shapes={})

        try:
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls(shapes={})

        shapes: dict[str, CatalogEntry] = {}
        for entry_data in data.get("shapes", []):
            fp = entry_data.get("fingerprint", "")
            if not fp:
                continue
            entry = CatalogEntry(
                fingerprint=fp,
                target_kind=entry_data.get("target_kind", ""),
                confirmed_in=tuple(entry_data.get("confirmed_in", [])),
                confidence=entry_data.get("confidence", 0.8),
                required_properties=frozenset(entry_data.get("required_properties", [])),
            )
            shapes[fp] = entry

        return cls(shapes=shapes)

    def lookup(self, fingerprint: str) -> CatalogEntry | None:
        """Look up a fingerprint in the catalog."""
        return self.shapes.get(fingerprint)


def compute_schema_fingerprint(
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> str:
    """Compute a structural fingerprint from schema properties.

    Returns sorted name:type pairs with ? suffix for optional properties.
    Example: "key:string?,name:string,namespace:string?"
    """
    if not properties:
        return ""
    required_set = set(required) if required else set()
    parts: list[str] = []
    for prop_name in sorted(properties.keys()):
        prop_schema = properties[prop_name]
        prop_type = prop_schema.get("type", "string") if isinstance(prop_schema, dict) else "string"
        suffix = "" if prop_name in required_set else "?"
        parts.append(f"{prop_name}:{prop_type}{suffix}")
    return ",".join(parts)


# Module-level shape catalog singleton.
_SHAPE_CATALOG: ShapeCatalog | None = None


def _get_shape_catalog() -> ShapeCatalog:
    """Lazy-load shape catalog (singleton)."""
    global _SHAPE_CATALOG  # noqa: PLW0603
    if _SHAPE_CATALOG is None:
        _SHAPE_CATALOG = ShapeCatalog.load()
    return _SHAPE_CATALOG


# Workload Kinds for scale subresource resolution.
_SCALE_WORKLOAD_KINDS: frozenset[str] = frozenset({
    "Deployment", "StatefulSet", "DaemonSet", "ReplicaSet",
})


def detect_scale_subresource(
    crd_spec: dict,
    kind: str,
    group: str,
    registry: KindRegistry,
) -> list[ClassifiedField]:
    """Detect scale subresource declarations in CRD spec (C20).

    Operates on CRD-level metadata, not individual walked fields.
    Called once per CRD from crd_dep.py during processing.
    """
    results: list[ClassifiedField] = []

    for version in crd_spec.get("versions", []):
        if not isinstance(version, dict):
            continue

        subresources = version.get("subresources")
        if not isinstance(subresources, dict):
            continue
        scale = subresources.get("scale")
        if not isinstance(scale, dict):
            continue

        spec_path = scale.get("specReplicasPath", "")
        status_path = scale.get("statusReplicasPath", "")

        # Validate paths are non-empty strings.
        if not spec_path or not isinstance(spec_path, str):
            continue
        if not status_path or not isinstance(status_path, str):
            continue

        # Validate path prefixes.
        if not spec_path.startswith(".spec."):
            continue
        if not status_path.startswith(".status."):
            continue

        # Attempt to resolve the target workload Kind from spec properties.
        target_kind = _resolve_scale_target(version, registry)
        if target_kind is None:
            continue

        target_group = registry.group_for_kind(target_kind) or ""
        results.append(ClassifiedField(
            field="scale_subresource",
            role="output_declaration",
            confidence=0.9,
            field_type="subresource",
            target_kind=target_kind,
            target_group=target_group,
            detection_source="ref_detector:scale_subresource",
            fact_shape="identity",
        ))

    return results


def _resolve_scale_target(
    version: dict,
    registry: KindRegistry,
) -> str | None:
    """Scan CRD spec properties for a field referencing a workload Kind."""
    schema = version.get("schema", {})
    v3 = schema.get("openAPIV3Schema", {})
    spec_props = (
        v3.get("properties", {})
        .get("spec", {})
        .get("properties", {})
    )
    if not spec_props:
        return None

    for field_name in spec_props:
        is_ref, ref_kind, _, _ = registry.is_ref_field(field_name)
        if is_ref and ref_kind and ref_kind in _SCALE_WORKLOAD_KINDS:
            return ref_kind

    return None


def detect_kubernetes_extensions(
    field: WalkedField,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Detect dependency signals from x-kubernetes-* extensions (C32).

    Returns ClassifiedField or None. For x-kubernetes-embedded-resource: true,
    returns immediately (exclusive). For list-map matches, returns additive result.
    """
    schema = field.schema

    # 1. Embedded resource check (exclusive, 0.95).
    if schema.get("x-kubernetes-embedded-resource") is True:
        target_kind = None
        properties = schema.get("properties", {})
        kind_prop = properties.get("kind", {}) if isinstance(properties, dict) else {}
        if isinstance(kind_prop, dict):
            kind_enum = kind_prop.get("enum")
            if isinstance(kind_enum, list) and len(kind_enum) == 1:
                target_kind = kind_enum[0]
            # Multiple values = passthrough, target_kind stays None.

        # Set the ManifestFlags passthrough flag via the caller's accumulator.
        # Do NOT emit a ClassifiedField with an invalid role. Instead:
        # - If target_kind is resolved (single Kind enum), emit as input_ref.
        # - If target_kind is None (true passthrough), only set the flag — no
        #   ClassifiedField, since we cannot produce a valid edge without a target.
        if target_kind:
            return ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=0.95,
                field_type=schema.get("type", "object"),
                target_kind=target_kind,
                detection_source="ref_detector:kubernetes_ext_embedded",
                fact_shape="identity",
            )
        # True passthrough (no specific target Kind). Signal via return value
        # that caller should set ManifestFlags.accepts_arbitrary_resources.
        # Return a config_field so the field is recorded but no edge is created.
        return ClassifiedField(
            field=field.path,
            role="config_field",
            confidence=0.95,
            field_type=schema.get("type", "object"),
            target_kind=None,
            detection_source="ref_detector:kubernetes_ext_embedded",
            fact_shape="identity",
        )

    # 2. List-map check (additive, 0.8).
    if (
        schema.get("x-kubernetes-list-type") == "map"
        and schema.get("x-kubernetes-list-map-keys") == ["name"]
    ):
        items = schema.get("items", {})
        if isinstance(items, dict):
            items_props = items.get("properties", {})
            if items_props:
                for _shape_name, fingerprint in WORKLOAD_SHAPES.items():
                    if _match_workload_fingerprint(items_props, fingerprint):
                        return ClassifiedField(
                            field=field.path,
                            role="output_declaration",
                            confidence=0.8,
                            field_type=schema.get("type", "array"),
                            target_kind=fingerprint.produces_kind,
                            target_group=registry.group_for_kind(fingerprint.produces_kind) or "",
                            detection_source="ref_detector:kubernetes_ext_list_map",
                            fact_shape="identity",
                        )

    # 3. Int-or-string check (no edge).
    if schema.get("x-kubernetes-int-or-string") is True:
        return None

    return None


def detect_cataloged_shape(
    field: WalkedField,
    shape_catalog: ShapeCatalog,
) -> ClassifiedField | None:
    """Match a walked field against the pre-computed shape catalog (C30).

    Returns ClassifiedField with role="input_ref" or None.
    """
    schema = field.schema
    properties = schema.get("properties")
    if not properties or not isinstance(properties, dict):
        return None

    required = schema.get("required", [])
    fingerprint = compute_schema_fingerprint(properties, required)
    if not fingerprint:
        return None

    entry = shape_catalog.lookup(fingerprint)
    if entry is None:
        return None

    # Verify all required_properties from catalog are present.
    for req_prop in entry.required_properties:
        if req_prop not in properties:
            return None

    return ClassifiedField(
        field=field.path,
        role="input_ref",
        confidence=entry.confidence,
        field_type=schema.get("type", "object"),
        target_kind=entry.target_kind,
        target_group="",
        detection_source="ref_detector:cataloged_shape",
        fact_shape="identity",
        target_field="name",
    )


# Precompiled K8s name patterns for fast comparison.
_K8S_NAME_PATTERN_SET: frozenset[str] = frozenset(K8S_NAME_PATTERNS)


def _is_k8s_name_pattern(pattern: str) -> bool:
    """Check if a schema pattern matches a known K8s DNS-name pattern."""
    return pattern in _K8S_NAME_PATTERN_SET


def detect_constraint_fk(
    field: WalkedField,
    registry: KindRegistry,
    parent_properties: dict[str, dict] | None = None,
) -> ClassifiedField | None:
    """Detect resource references from value constraints + sibling evidence (C29).

    Requires BOTH an explicit K8s DNS-name pattern (regex or format) AND a
    namespace sibling. Length-only constraints are NOT sufficient.
    """
    schema = field.schema

    # Step 1: Type check.
    if schema.get("type") != "string":
        return None

    # Step 2: Self-exclusion.
    if field.name.lower() == "namespace":
        return None

    # Step 3: DNS-name signal check (explicit pattern or format required).
    has_dns_signal = False
    schema_pattern = schema.get("pattern", "")
    if schema_pattern and _is_k8s_name_pattern(schema_pattern):
        has_dns_signal = True
    if not has_dns_signal:
        schema_format = schema.get("format", "")
        if schema_format and schema_format in K8S_FORMAT_ALLOWLIST:
            has_dns_signal = True
    if not has_dns_signal:
        return None

    # Step 4: Namespace sibling check.
    if parent_properties is None:
        return None

    has_namespace = False
    has_kind = False
    for prop_name, prop_schema in parent_properties.items():
        if not isinstance(prop_schema, dict):
            continue
        if prop_name.lower() == "namespace" and prop_name.lower() == "namespace":
            # Exact case-insensitive match on "namespace".
            if prop_schema.get("type") == "string":
                has_namespace = True
        if prop_name.lower() == "kind":
            has_kind = True

    if not has_namespace:
        return None

    # Step 5: Confidence computation.
    confidence = 0.75
    if has_kind:
        confidence = 0.80

    return ClassifiedField(
        field=field.path,
        role="input_ref",
        confidence=confidence,
        field_type="string",
        target_kind=None,
        detection_source="ref_detector:constraint_fk",
        fact_shape="identity",
    )


def _match_workload_fingerprint(
    properties: dict[str, dict],
    fingerprint: WorkloadFingerprint,
    is_flattened: bool = False,
) -> bool:
    """Check if schema properties match a workload fingerprint.

    Used by both detect_embedded_workload and detect_kubernetes_extensions.
    """
    # Check required properties.
    for req in fingerprint.required_properties:
        if req not in properties:
            return False

    # Container shape validation (PodTemplateSpec).
    if fingerprint.container_shape:
        containers = properties.get("containers", {})
        if not isinstance(containers, dict):
            return False
        if containers.get("type") != "array":
            return False
        items = containers.get("items", {})
        if not isinstance(items, dict):
            return False
        item_props = items.get("properties", {})
        for cs_prop in fingerprint.container_shape:
            if cs_prop not in item_props:
                return False

    # Count total matches (required + optional).
    match_count = len(fingerprint.required_properties)
    for opt in fingerprint.optional_properties:
        if opt in properties:
            match_count += 1

    # Higher threshold for flattened patterns.
    effective_min = fingerprint.min_match_count + 1 if is_flattened else fingerprint.min_match_count

    return match_count >= effective_min


def detect_embedded_workload(
    field: WalkedField,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Detect fields matching well-known K8s type shapes (C22).

    Checks schema properties of the walked field with nesting-aware matching.
    Returns ClassifiedField with role="output_declaration" or None.
    """
    schema = field.schema
    top_props = schema.get("properties", {})
    if not top_props and not isinstance(top_props, dict):
        return None

    for shape_name, fingerprint in WORKLOAD_SHAPES.items():
        # Standard nesting: check field.spec.properties.
        nested_spec = top_props.get("spec", {})
        nested_props = None
        if isinstance(nested_spec, dict) and nested_spec.get("type") == "object":
            candidate = nested_spec.get("properties", {})
            if candidate:
                nested_props = candidate

        if nested_props is not None:
            if _match_workload_fingerprint(nested_props, fingerprint, is_flattened=False):
                return ClassifiedField(
                    field=field.path,
                    role="output_declaration",
                    confidence=0.8,
                    field_type=schema.get("type", "object"),
                    target_kind=fingerprint.produces_kind,
                    target_group=registry.group_for_kind(fingerprint.produces_kind) or "",
                    detection_source="ref_detector:embedded_workload",
                    fact_shape="identity",
                )

        # Flattened: check field.properties directly (higher threshold).
        if top_props:
            if _match_workload_fingerprint(top_props, fingerprint, is_flattened=True):
                return ClassifiedField(
                    field=field.path,
                    role="output_declaration",
                    confidence=0.8,
                    field_type=schema.get("type", "object"),
                    target_kind=fingerprint.produces_kind,
                    target_group=registry.group_for_kind(fingerprint.produces_kind) or "",
                    detection_source="ref_detector:embedded_workload",
                    fact_shape="identity",
                )

    return None


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
        # Guard: if the field is type: object with properties, verify it has
        # reference-shaped children (name, key, namespace). Fields like
        # "authSecretRef" can be wrapper objects containing nested SecretRefs
        # rather than direct Secret references. Skip these — the walker will
        # recurse into children and detect the actual refs.
        if schema.get("type") == "object" and "properties" in schema:
            props = schema["properties"]
            ref_indicators = {"name", "key", "namespace", "apiVersion", "kind", "apiGroup"}
            if not any(ind in props for ind in ref_indicators):
                # Wrapper object — don't classify as ref, let walker recurse.
                return None

        cross_ns = detect_namespace(field)
        # Structural objects with ref indicators block descendants;
        # string-type fields have no children so the flag is irrelevant.
        is_structural = (schema.get("type") == "object" and "properties" in schema)
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
            blocks_descendants=is_structural,
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
                    blocks_descendants=True,
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


def detect_secret_key_selector(
    field: WalkedField,
) -> ClassifiedField | None:
    """Detect SecretKeySelector shape: {key: string, name: string, namespace?: string}.

    This K8s pattern indicates a reference to a specific key within a Secret.
    Field names vary widely (apiKeyRef, userRef, authRef, passcodeRef, etc.)
    so we match purely on structural shape, not field naming.

    Confidence: 0.85 (strong structural evidence).
    """
    schema = field.schema
    if schema.get("type") != "object":
        return None

    properties = schema.get("properties")
    if not properties or not isinstance(properties, dict):
        return None

    # Must have both 'key' and 'name' as string properties.
    key_prop = properties.get("key")
    name_prop = properties.get("name")
    if not key_prop or not isinstance(key_prop, dict) or key_prop.get("type") != "string":
        return None
    if not name_prop or not isinstance(name_prop, dict) or name_prop.get("type") != "string":
        return None

    # All other properties (if any) must be strings or known
    # SecretKeySelector fields to avoid matching generic objects
    # that happen to have key+name. The K8s SecretKeySelector type
    # includes an `optional` boolean field.
    _SKS_KNOWN_FIELDS = {"key", "name", "namespace", "optional"}
    for prop_name, prop_schema in properties.items():
        if prop_name in _SKS_KNOWN_FIELDS:
            continue
        if isinstance(prop_schema, dict) and prop_schema.get("type") != "string":
            return None

    cross_ns = "namespace" in properties

    return ClassifiedField(
        field=field.path,
        role="input_ref",
        confidence=0.85,
        field_type="object",
        target_kind="Secret",
        target_group="core",
        required=field.required,
        cross_namespace=cross_ns,
        description=schema.get("description", ""),
        detection_source="ref_detector:secret_key_selector",
        fact_shape="identity",
        target_field="name",
        blocks_descendants=True,
    )


def detect_parent_kind_name(
    field: WalkedField,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Detect refs where parent field name implies the Kind (C12 port).

    When a string field named "name" sits inside an object/array whose parent
    field name can be depluralized to a registered Kind, emit an input_ref.

    Examples:
        templateFrom.secret.name → Secret (parent "secret")
        routes.middlewares.name → Middleware (parent "middlewares")
        routes.services.name → Service (parent "services")
        auth.serviceAccount.name → ServiceAccount (parent "serviceAccount")

    Confidence: 0.80 (structural + naming convention).
    """
    # Only triggers on string fields named "name".
    if field.name != "name" or field.schema.get("type") != "string":
        return None

    # Suppress list-map merge keys in inline K8s objects (volumes, containers).
    if field.name == "name" and is_inline_object_name(field):
        return None

    # Extract the immediate parent field name from the parent_path.
    parent_path = field.parent_path
    if "." not in parent_path:
        return None
    parent_name = parent_path.rsplit(".", 1)[-1]
    if not parent_name:
        return None

    # Try to resolve parent name to a Kind:
    # 1. Direct PascalCase (serviceAccount → ServiceAccount)
    # 2. Depluralize then PascalCase (middlewares → Middleware, secrets → Secret)
    candidates: list[str] = []

    # Direct: capitalize first letter.
    candidates.append(parent_name[0].upper() + parent_name[1:])

    # Depluralize: strip trailing "s" or "es".
    lower = parent_name.lower()
    if lower.endswith("ies"):
        candidates.append(lower[:-3].capitalize() + "y")
    elif lower.endswith("ses") or lower.endswith("xes") or lower.endswith("zes"):
        candidates.append(lower[:-2].capitalize())
    elif lower.endswith("es"):
        candidates.append(lower[:-2].capitalize())
        candidates.append(lower[:-1].capitalize())
    elif lower.endswith("s") and not lower.endswith("ss"):
        candidates.append(lower[:-1].capitalize())

    all_kinds = registry.all_kinds()
    all_kinds_lower = {k.lower(): k for k in all_kinds}

    for candidate in candidates:
        # Try exact match.
        if candidate in all_kinds:
            target_group = registry.group_for_kind(candidate) or ""
            return ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=0.80,
                field_type="string",
                target_kind=candidate,
                target_group=target_group,
                required=field.required,
                description=field.schema.get("description", ""),
                detection_source="ref_detector:parent_kind_name",
                fact_shape="identity",
                target_field="name",
            )
        # Try case-insensitive match.
        canonical = all_kinds_lower.get(candidate.lower())
        if canonical:
            target_group = registry.group_for_kind(canonical) or ""
            return ClassifiedField(
                field=field.path,
                role="input_ref",
                confidence=0.80,
                field_type="string",
                target_kind=canonical,
                target_group=target_group,
                required=field.required,
                description=field.schema.get("description", ""),
                detection_source="ref_detector:parent_kind_name",
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
                        blocks_descendants=True,
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
                    blocks_descendants=True,
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


_K8S_API_CONSTANTS: frozenset[str] = frozenset({
    "Orphan", "Background", "Foreground",
    "Cluster", "Namespaced",
    "Allow", "Deny", "Ignore",
})

_KIND_LIKE_FIELD_NAMES: frozenset[str] = frozenset({
    "kind", "targetKind", "resourceKind", "apiKind",
})


def detect_enum_kind(
    field: WalkedField,
    registry: KindRegistry,
    sibling_fields: dict[str, Any] | None = None,
) -> list[ClassifiedField]:
    """Detect enum values matching known Kinds (C18).

    The enum field is a discriminator, not a ref. When a sibling 'name'
    field exists, the ref points to the sibling, not the enum.

    Guards (section-08):
    - Field name must be kind-like (kind, targetKind, resourceKind, type)
    - K8s API constants (Orphan, Background, etc.) are filtered before matching
    - Kindness ratio (matched/total after filtering) must be >= 0.6

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

    # Guard: field name must be kind-like.
    if field.name not in _KIND_LIKE_FIELD_NAMES:
        return []

    # Filter out K8s API constants before matching.
    filtered_values = [v for v in enum_values if isinstance(v, str) and v not in _K8S_API_CONSTANTS]
    if not filtered_values:
        return []

    # Build case-insensitive lookup from registry.
    all_kinds = registry.all_kinds()
    kind_lower_map: dict[str, str] = {k.lower(): k for k in all_kinds}

    matched_kinds: list[str] = []
    for val in filtered_values:
        canonical = kind_lower_map.get(val.lower())
        if canonical:
            matched_kinds.append(canonical)

    if not matched_kinds:
        return []

    # Kindness ratio guard: matched / total filtered must be >= 0.8.
    match_ratio = len(matched_kinds) / len(filtered_values)
    if match_ratio < 0.8:
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
    """Classify status fields as output_declarations (C10, C27).

    Four tiers (checked in order):
    0. KindRegistry longest-match (C27) — confidence 0.85, "status_addressability"
    1. Conditions pattern — confidence 0.9, fact_shape="lifecycle"
    2. Kind substring in field name — confidence 0.85, fact_shape="identity"
    3. Generic status field — confidence 0.6 (BELOW 0.7 threshold)
    """
    schema = field.schema
    field_type = schema.get("type", "string")

    # Tier 0 (C27): KindRegistry longest-match for status field names.
    is_ref, ref_kind, ref_plural, ref_group = registry.is_ref_field(field.name)
    if is_ref and ref_kind:
        return ClassifiedField(
            field=field.path,
            role="output_declaration",
            confidence=0.85,
            field_type=field_type,
            target_kind=ref_kind,
            target_group=ref_group,
            detection_source="ref_detector:status_addressability",
            fact_shape="identity",
            target_field="name",
        )

    # Tier 1: Conditions pattern (most specific structural pattern).
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

    # Tier 2: Kind substring in field name (fallback from Phase 2).
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


def split_camel_case(text: str) -> list[str]:
    """Split camelCase/PascalCase text into tokens.

    Handles acronyms correctly: 'serverURL' -> ['server', 'URL'].
    Uses two-pass regex for standard camelCase splitting.
    """
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.split("_")


# Phase 3 detection source prefixes (Rule 2 scope guard).
_PHASE3_SOURCES = frozenset({
    "ref_detector:ref_tuple",
    "ref_detector:example_kind",
    "ref_detector:apigroup_literal",
})

# Structural K8s reference indicator property names.
_STRUCTURAL_MARKERS = frozenset({"namespace", "kind", "apiGroup"})


def _rule_target_kind_not_at_word_boundary(
    field: WalkedField,
    classification: ClassifiedField,
) -> bool:
    """Rule 1: Suppress when target_kind is not a complete camelCase token.

    Exempt: detectors that resolve Kind from schema data (enum values)
    rather than field names. Passthrough manifests and enum_kind both
    resolve from enum -- the field name is unrelated to the target Kind.
    """
    target_kind = classification.target_kind
    if not target_kind:
        return False

    # Detectors that resolve Kind from enum values or structural evidence,
    # not field names.
    exempt_sources = {
        "ref_detector:passthrough_manifest",
        "ref_detector:enum_kind",
        "ref_detector:example_kind",
        "ref_detector:apigroup_literal",
        "ref_detector:kubernetes_ext_embedded",
        "ref_detector:kubernetes_ext_list_map",
        "ref_detector:embedded_workload",
        "ref_detector:cataloged_shape",
        "ref_detector:constraint_fk",
    }
    if classification.detection_source in exempt_sources:
        return False

    tokens = split_camel_case(field.name)
    target_lower = target_kind.lower()

    for token in tokens:
        token_lower = token.lower()
        if token_lower == target_lower:
            return False  # Exact match -> do not suppress
        # Depluralize: remove trailing 's' and check.
        if token_lower.endswith("s") and token_lower[:-1] == target_lower:
            return False  # Depluralized match -> do not suppress

    return True  # target_kind not found as token -> suppress


def _rule_kind_collision_no_structural_context(
    field: WalkedField,
    classification: ClassifiedField,
) -> bool:
    """Rule 2: Suppress Phase 3 detections on fields without structural context.

    ONLY applies to Phase 3 detector sources. Phase 2 sources are exempt.
    """
    # Scope guard: only Phase 3 detectors.
    if classification.detection_source not in _PHASE3_SOURCES:
        return False

    schema = field.schema
    field_type = schema.get("type", "")

    # Primitive types cannot be structural references.
    if field_type in ("string", "integer", "boolean", "number"):
        return True

    # Object type: check for structural markers.
    if field_type == "object":
        properties = schema.get("properties", {})
        if not any(marker in properties for marker in _STRUCTURAL_MARKERS):
            return True

    return False


def _rule_nested_metadata_self_reference(
    field: WalkedField,
    classification: ClassifiedField,
) -> bool:
    """Rule 3: Suppress nested metadata.name/metadata.namespace self-references."""
    segments = field.path.split(".")
    for i in range(len(segments) - 1):
        if segments[i] == "metadata" and segments[i + 1] in ("name", "namespace"):
            if i > 1:  # metadata at depth > 1
                return True
    return False


_CREDENTIAL_VALUE_RE: re.Pattern = re.compile(
    r"(?i)^("
    r"password|passwd|"
    r"client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|bearer[_-]?token|id[_-]?token|"
    r"token|"
    r"api[_-]?key|apikey|"
    r"secret[_-]?key|"
    r"access[_-]?key[_-]?id|secret[_-]?access[_-]?key|"
    r"authorization"
    r")$"
)


def _rule_credential_value_field(
    field: WalkedField,
    classification: ClassifiedField,
) -> bool:
    """Rule 4: Suppress string credential value fields.

    String fields whose name matches credential patterns (password, token,
    apiKey, clientSecret, bearerToken, etc.) hold opaque values, not
    resource names. Object-typed fields are exempt -- those are typically
    SecretKeySelector-shaped refs (e.g., tokenSecretRef).
    """
    if field.schema.get("type") != "string":
        return False
    return bool(_CREDENTIAL_VALUE_RE.match(field.name))


# Suppression rules: list of (predicate_function, rule_name) tuples.
# Extensible design -- new FP patterns are added as new tuples.
_SUPPRESSION_RULE_LIST: list[tuple[Any, str]] = [
    (_rule_target_kind_not_at_word_boundary, "target_kind_not_at_word_boundary"),
    (_rule_kind_collision_no_structural_context, "kind_collision_no_structural_context"),
    (_rule_nested_metadata_self_reference, "nested_metadata_self_reference"),
    (_rule_credential_value_field, "credential_value_field"),
]


def suppress_false_positives(
    field: WalkedField,
    classifications: list[ClassifiedField],
) -> list[ClassifiedField]:
    """Post-filter to suppress known false positive patterns (C28).

    Suppressed items are KEPT but downgraded:
    - role changed to "config_field"
    - confidence set to 0.1 (below 0.7 threshold)
    - detection_source updated to "suppressed:{original}:{rule}"

    Returns the full list with suppressions applied.
    """
    if not classifications:
        return classifications

    result: list[ClassifiedField] = []
    for c in classifications:
        suppressed = False
        for predicate, rule_name in _SUPPRESSION_RULE_LIST:
            if predicate(field, c):
                # Downgrade: create a new ClassifiedField with suppression markers.
                result.append(ClassifiedField(
                    field=c.field,
                    role="config_field",
                    confidence=0.1,
                    field_type=c.field_type,
                    target_kind=c.target_kind,
                    target_group=c.target_group,
                    required=c.required,
                    cross_namespace=c.cross_namespace,
                    description=c.description,
                    detection_source=f"suppressed:{c.detection_source}:{rule_name}",
                    fact_shape=c.fact_shape,
                    target_field=c.target_field,
                ))
                suppressed = True
                break  # First matching rule wins
        if not suppressed:
            result.append(c)
    return result


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


def _merge_additive_results(
    results: list[ClassifiedField],
) -> list[ClassifiedField]:
    """Merge additive detector results, keeping highest confidence per dedup key.

    Dedup key: (field_path, role, target_kind).
    If equal confidence, prefer result from earlier pipeline step (lower index in input list).
    Input list preserves pipeline ordering (earlier steps come first).
    """
    if not results:
        return results

    best: dict[tuple[str, str, str | None], ClassifiedField] = {}
    for c in results:
        key = (c.field, c.role, c.target_kind)
        existing = best.get(key)
        if existing is None or c.confidence > existing.confidence:
            best[key] = c
        # Equal confidence: earlier entry wins (already in dict).
    return list(best.values())


_SEMANTIC_FIELD_MAP: dict[str, tuple[str, str, float]] = {
    # field_name -> (target_kind, target_group, confidence)
    "credentialName": ("Secret", "core", 0.90),
    "tlsSecret": ("Secret", "core", 0.90),
}


def detect_semantic_field(
    field: WalkedField,
    registry: KindRegistry,
) -> ClassifiedField | None:
    """Detect refs via curated semantic field name map.

    Lookup table for well-known field names that reference specific Kinds
    without naming them via standard suffix patterns. Only fires on
    type: string fields with exact name match.

    Returns ClassifiedField or None if no match.
    """
    if field.schema.get("type") != "string":
        return None

    entry = _SEMANTIC_FIELD_MAP.get(field.name)
    if entry is None:
        return None

    target_kind, target_group, confidence = entry
    return ClassifiedField(
        field=field.path,
        role="input_ref",
        confidence=confidence,
        field_type=field.schema.get("type", "string"),
        target_kind=target_kind,
        target_group=target_group,
        required=field.required,
        description=field.schema.get("description", ""),
        detection_source="ref_detector:semantic_field",
        fact_shape="identity",
    )


def detect_fuzzy_kind_name(
    field: WalkedField,
    registry: KindRegistry,
    current_group: str,
    current_service: str,
) -> ClassifiedField | None:
    """Detect refs via fuzzy Kind name matching (plural, suffix, camel, bare).

    Called only when no prior detector produced an input_ref classification.
    Uses KindRegistry.fuzzy_resolve() to find candidate Kind matches.

    Type guards: only string or array[string] fields.
    Confidence: candidate score * field.depth_confidence must reach 0.7.
    """
    field_type = field.schema.get("type")
    if field_type == "string":
        pass  # Proceed.
    elif field_type == "array":
        items_type = field.schema.get("items", {}).get("type")
        if items_type != "string":
            return None
    else:
        return None

    candidates = registry.fuzzy_resolve(
        field.name,
        scope_service=current_service,
        require_unique=True,
        sibling_names=field.sibling_names,
    )
    if not candidates:
        return None

    best = candidates[0]
    final_confidence = best.score * field.depth_confidence
    if final_confidence < 0.7:
        return None

    return ClassifiedField(
        field=field.path,
        role="input_ref",
        confidence=final_confidence,
        field_type=field.schema.get("type", "string"),
        target_kind=best.kind,
        target_group=best.api_group,
        required=field.required,
        description=field.schema.get("description", ""),
        detection_source=f"ref_detector:fuzzy_kind_name:{best.match_type}",
        fact_shape="identity",
        target_field="name",
    )


def classify_walked_field(
    field: WalkedField,
    registry: KindRegistry,
    kind: str,
    group: str,
    sibling_fields: dict[str, Any] | None = None,
    manifest_flags: ManifestFlags | None = None,
    current_service: str = "",
) -> list[ClassifiedField]:
    """Top-level orchestrator for spec field classification.

    Runs the detector cascade via _classify_walked_field_inner, then applies
    depth confidence multiplication as a centralized post-processing step.
    """
    results = _classify_walked_field_inner(
        field, registry, kind, group,
        sibling_fields=sibling_fields,
        manifest_flags=manifest_flags,
        current_service=current_service,
    )

    # Centralized depth confidence multiplication.
    # Applied to ALL detector results uniformly so that:
    # 1. Deep fields get reduced confidence without per-detector changes.
    # 2. Future detectors automatically receive depth scaling.
    # 3. The 0.7 emission floor (enforced downstream) naturally prunes
    #    low-confidence deep matches.
    if field.depth_confidence < 1.0:
        for classified in results:
            classified.confidence *= field.depth_confidence

    return results


def _classify_walked_field_inner(
    field: WalkedField,
    registry: KindRegistry,
    kind: str,
    group: str,
    sibling_fields: dict[str, Any] | None = None,
    manifest_flags: ManifestFlags | None = None,
    current_service: str = "",
) -> list[ClassifiedField]:
    """Internal detector cascade (pre-depth-multiplication).

    Runs detectors in priority order (remediation-updated pipeline):
    Step  0: Side-effect dictionary (0.95) — *Name override
    Step  1: detect_ref (0.9) — exclusive
    Step  2: detect_secret_key_selector (0.85) — exclusive
    Step  3: detect_parent_kind_name (0.80) — exclusive
    Step  4: detect_ref_tuple (0.85) — exclusive
    Step  5: detect_kubernetes_extensions (0.8-0.95) — C32
             embedded-resource: exclusive at 0.95
             list-map: additive at 0.8
    Step  6: detect_enum_kind (0.95)
    Step  7: detect_example_kinds (0.8) — additive
    Step  8: detect_apigroup_literal (0.85) — additive
    Step  9: detect_passthrough_manifest (0.95)
    Step 10: detect_constraint_fk (0.75) — C29, additive
    Step 11: detect_embedded_workload (0.8) — C22, additive
    Step 12: detect_cataloged_shape (0.8-0.85) — C30, additive
    Step 12.5: detect_fuzzy_kind_name — fuzzy Kind matching (section-06)
    Step 12.6: detect_semantic_field (0.90) — curated field name map (section-07)
    Step 13: Side-effect NLP
    Step 14: readOnly → output_declaration (0.8)
    Step 15: Default config_field
    Step 16: suppress_false_positives — post-filter

    Note: detect_status_output is NOT called here — it is invoked
    separately on status fields by callers.
    detect_scale_subresource is called from crd_dep.py.
    extract_webhook_dependencies is called from RbacDepAdapter.

    Args:
        field: WalkedField from schema walker.
        registry: KindRegistry instance.
        kind: The source CRD's Kind name.
        group: The source CRD's API group.
        sibling_fields: Parent object's properties (for enum_kind and constraint_fk).
        manifest_flags: Optional accumulator for manifest-level flags.
            If provided, passthrough detection will mutate it.
            If None, passthrough detection still runs but the flag is lost.

    Returns:
        List of ClassifiedField (usually 1 item; multiple for enum_kind).
    """
    # Step 0: Side-effect dictionary for *Name fields.
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

    # Step 1: Structural ref detection (exclusive).
    ref_result = detect_ref(field, registry)
    if ref_result is not None:
        return [ref_result]

    # Step 2: SecretKeySelector shape detection (exclusive).
    sks_result = detect_secret_key_selector(field)
    if sks_result is not None:
        return [sks_result]

    # Step 3: Parent-name → Kind resolution (exclusive).
    parent_result = detect_parent_kind_name(field, registry)
    if parent_result is not None:
        return [parent_result]

    # Step 4: Reference tuple detection (C19, exclusive).
    tuple_results = detect_ref_tuple(field, registry)
    if tuple_results:
        return tuple_results

    # --- Additive detectors (steps 5-12): results accumulate ---
    additive_results: list[ClassifiedField] = []

    # Step 3: x-kubernetes extension fingerprinting (C32).
    ext_result = detect_kubernetes_extensions(field, registry)
    if ext_result is not None:
        if ext_result.detection_source == "ref_detector:kubernetes_ext_embedded":
            # Exclusive: embedded-resource at 0.95.
            # If no target_kind, this is a true passthrough — set the flag.
            if not ext_result.target_kind and manifest_flags is not None:
                manifest_flags.accepts_arbitrary_resources = True
            return [ext_result]
        # Additive: list-map at 0.8.
        additive_results.append(ext_result)

    # Step 4: Enum Kind detection.
    enum_results = detect_enum_kind(field, registry, sibling_fields)
    additive_results.extend(enum_results)

    # Step 5: Example/default Kind extraction (C24).
    example_results = detect_example_kinds(field, registry)
    additive_results.extend(example_results)

    # Step 6: API group literal detection (C25).
    apigroup_results = detect_apigroup_literal(field, registry)
    additive_results.extend(apigroup_results)

    # Step 7: Passthrough manifest detection (C26).
    passthrough_results = detect_passthrough_manifest(field, registry, manifest_flags)
    additive_results.extend(passthrough_results)

    # Step 8: Constraint-based FK inference (C29, additive).
    fk_result = detect_constraint_fk(field, registry, parent_properties=sibling_fields)
    if fk_result is not None:
        additive_results.append(fk_result)

    # Step 9: Embedded workload shape matching (C22, additive).
    workload_result = detect_embedded_workload(field, registry)
    if workload_result is not None:
        additive_results.append(workload_result)

    # Step 10: Cross-CRD shape catalog matching (C30, additive).
    catalog = _get_shape_catalog()
    catalog_result = detect_cataloged_shape(field, catalog)
    if catalog_result is not None:
        additive_results.append(catalog_result)

    # Merge additive results, then deduplicate and suppress.
    if additive_results:
        merged = _merge_additive_results(additive_results)
        merged = _deduplicate_classifications(merged)
        return suppress_false_positives(field, merged)

    # Step 10.5: Fuzzy Kind name matching (between additive block and NLP fallback).
    # Only fires when no prior detector produced an input_ref.
    fuzzy_result = detect_fuzzy_kind_name(field, registry, group, current_service)
    if fuzzy_result is not None:
        return suppress_false_positives(field, [fuzzy_result])

    # Step 10.6: Semantic field map lookup.
    # Curated field names that reference specific Kinds without standard suffixes.
    semantic_result = detect_semantic_field(field, registry)
    if semantic_result is not None:
        return [semantic_result]

    # Step 11: Side-effect NLP for *Name fields (non-dictionary).
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

    # Step 12: readOnly field → output_declaration.
    if field.schema.get("readOnly") is True:
        return [ClassifiedField(
            field=field.path,
            role="output_declaration",
            confidence=0.8,
            field_type=field.schema.get("type", "string"),
            required=field.required,
            description=field.schema.get("description", ""),
            detection_source="ref_detector:readonly",
            fact_shape="identity",
        )]

    # Step 13: Default — config_field.
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
