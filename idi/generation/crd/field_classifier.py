"""RESTler-adapted field classifier for CRD schemas.

Classifies CRD spec properties into roles:
- input_ref: consumer — needs an existing resource
- output_declaration: producer — operator creates this
- config_field: parameterization — no dep edges

Uses structural heuristics (0.9), description NLP (0.6),
and side-effect dictionary (0.95) in layered confidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from idi.generation.adapters.kubernetes_crd import (
    K8S_REF_PATTERNS,
    _COMPOUND_SUFFIXES,
    EXCLUDED_FIELDS,
)
from idi.generation.crd.side_effect_registry import classify_name_field


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


def classify_fields(
    spec_properties: dict[str, Any],
    spec_required: list[str],
    group: str,
    kind: str,
    prefix: str = "spec",
) -> list[ClassifiedField]:
    """Classify all spec properties into roles.

    Args:
        spec_properties: The properties dict from spec.
        spec_required: Required field names.
        group: CRD API group.
        kind: CRD Kind name.
        prefix: Dot-path prefix (default: "spec").

    Returns:
        List of ClassifiedField with roles assigned.
    """
    results: list[ClassifiedField] = []

    for prop_name, prop_schema in spec_properties.items():
        if not isinstance(prop_schema, dict):
            continue
        if prop_name in EXCLUDED_FIELDS:
            continue

        field_path = f"{prefix}.{prop_name}"
        field_type = prop_schema.get("type", "string")
        description = prop_schema.get("description", "")
        is_required = prop_name in spec_required

        classified = _classify_single_field(
            prop_name, prop_schema, field_path, field_type,
            description, is_required, group, kind,
        )
        results.append(classified)

    return results


def _classify_single_field(
    prop_name: str,
    prop_schema: dict[str, Any],
    field_path: str,
    field_type: str,
    description: str,
    is_required: bool,
    group: str,
    kind: str,
) -> ClassifiedField:
    """Classify a single field using layered heuristics."""

    lower_name = prop_name.lower()

    # 1. *Name fields — check side-effect registry first (dictionary 0.95 > structural 0.9).
    if lower_name.endswith("name") and field_type == "string":
        role, confidence = classify_name_field(
            field_path, group, kind, description,
        )
        if role == "output_declaration":
            # Look up what it produces from side-effect registry.
            from idi.generation.crd.side_effect_registry import get_side_effects
            effects = get_side_effects(group, kind)
            for eff in effects:
                if eff["field"] == field_path:
                    return ClassifiedField(
                        field=field_path, role="output_declaration",
                        confidence=confidence, field_type=field_type,
                        target_kind=eff["produces_kind"],
                        target_group=eff["produces_group"],
                        required=is_required, description=description,
                    )
            # NLP detected output but no dictionary entry — still output.
            return ClassifiedField(
                field=field_path, role="output_declaration",
                confidence=confidence, field_type=field_type,
                required=is_required, description=description,
            )
        if role == "input_ref":
            # Infer target from compound suffix.
            base = re.sub(r'[Nn]ame$', '', prop_name).lower()
            for suffix, resource in _COMPOUND_SUFFIXES.items():
                if base.endswith(suffix) or base == suffix:
                    return ClassifiedField(
                        field=field_path, role="input_ref",
                        confidence=confidence, field_type=field_type,
                        target_kind=_resource_to_kind(resource),
                        target_group=_resource_to_group(resource),
                        required=is_required, description=description,
                    )
            return ClassifiedField(
                field=field_path, role="input_ref",
                confidence=confidence, field_type=field_type,
                required=is_required, description=description,
            )
        # config_field fallthrough — fall to default at bottom.

    # 2. Check K8S_REF_PATTERNS (exact match, non-*Name fields only).
    if lower_name in K8S_REF_PATTERNS:
        target_resource = K8S_REF_PATTERNS[lower_name]
        target_kind = _resource_to_kind(target_resource)
        target_group = _resource_to_group(target_resource)
        cross_ns = _has_namespace_prop(prop_schema)
        return ClassifiedField(
            field=field_path, role="input_ref", confidence=0.9,
            field_type=field_type, target_kind=target_kind,
            target_group=target_group, required=is_required,
            cross_namespace=cross_ns, description=description,
        )

    # 3. Object with name property + *Ref suffix → input_ref.
    if (
        field_type == "object"
        and "name" in prop_schema.get("properties", {})
        and lower_name.endswith("ref")
    ):
        target_kind = _infer_kind_from_ref(prop_name)
        cross_ns = "namespace" in prop_schema.get("properties", {})
        return ClassifiedField(
            field=field_path, role="input_ref", confidence=0.9,
            field_type=field_type, target_kind=target_kind,
            target_group=group, required=is_required,
            cross_namespace=cross_ns, description=description,
        )

    # 4. Compound *Ref suffix (e.g., passwordSecretRef).
    if lower_name.endswith("ref"):
        base = re.sub(r'[Rr]ef$', '', prop_name).lower()
        for suffix, resource in _COMPOUND_SUFFIXES.items():
            if base.endswith(suffix) and base != suffix:
                target_kind = _resource_to_kind(resource)
                target_group = _resource_to_group(resource)
                cross_ns = _has_namespace_prop(prop_schema)
                return ClassifiedField(
                    field=field_path, role="input_ref", confidence=0.9,
                    field_type=field_type, target_kind=target_kind,
                    target_group=target_group, required=is_required,
                    cross_namespace=cross_ns, description=description,
                )

    # 5. Default: config_field.
    return ClassifiedField(
        field=field_path, role="config_field", confidence=0.5,
        field_type=field_type, required=is_required,
        description=description,
    )


# -- Helpers ----------------------------------------------------------------

_KIND_MAP = {
    "secrets": "Secret",
    "configmaps": "ConfigMap",
    "services": "Service",
    "serviceaccounts": "ServiceAccount",
    "persistentvolumes": "PersistentVolume",
    "persistentvolumeclaims": "PersistentVolumeClaim",
    "nodes": "Node",
    "namespaces": "Namespace",
    "endpoints": "Endpoint",
    "secretstores": "SecretStore",
    "clustersecretstores": "ClusterSecretStore",
    "ingressclasses": "IngressClass",
    "clusters": "Cluster",
    "externalsecrets": "ExternalSecret",
}

_CORE_RESOURCES = frozenset({
    "secrets", "configmaps", "services", "serviceaccounts",
    "persistentvolumes", "persistentvolumeclaims",
    "nodes", "namespaces", "endpoints",
})


def _resource_to_kind(resource: str) -> str:
    return _KIND_MAP.get(resource, resource.title().replace("s", "", 1))


def _resource_to_group(resource: str) -> str:
    return "core" if resource in _CORE_RESOURCES else ""


def _has_namespace_prop(schema: dict[str, Any]) -> bool:
    if schema.get("type") != "object":
        return False
    return "namespace" in schema.get("properties", {})


def _infer_kind_from_ref(field_name: str) -> str:
    """Infer Kind from a *Ref field name: issuerRef -> Issuer."""
    base = re.sub(r'[Rr]ef$', '', field_name)
    # PascalCase: first char already upper in most cases.
    if base and base[0].isupper():
        return base
    return base[0].upper() + base[1:] if base else ""
