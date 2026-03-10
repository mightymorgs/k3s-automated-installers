#!/usr/bin/env python3
"""Systematic edge detection audit across all 3 CRD services.

Walks every CRD spec with NO depth limit, identifies all fields that should
be cross-resource references, and compares against what the pipeline actually
detected. Categorizes root causes for every gap.

Usage:
    python3 platform-tools/idi/scripts/edge_detection_audit.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SPECS = {
    "cert-manager": ROOT / "catalog" / "specs" / "cert-manager-openapi.json",
    "external-secrets": ROOT / "catalog" / "specs" / "external-secrets-openapi.json",
    "traefik": ROOT / "catalog" / "specs" / "traefik-openapi.json",
}
SKILLS_DIR = ROOT / "catalog" / "skills" / "crd"

# All known resource Kinds (core K8s + CRD)
CORE_KINDS = {
    "Secret", "ConfigMap", "Service", "ServiceAccount",
    "PersistentVolumeClaim", "PersistentVolume", "Namespace", "Node",
    "Pod", "Endpoint", "Deployment", "StatefulSet", "DaemonSet",
    "Job", "CronJob", "Ingress", "IngressClass", "StorageClass",
    "ClusterRole", "ClusterRoleBinding", "Role", "RoleBinding",
    "NetworkPolicy", "ResourceQuota", "LimitRange",
    "HorizontalPodAutoscaler", "ReplicaSet",
}

CRD_KINDS = {
    "Certificate", "CertificateRequest", "Issuer", "ClusterIssuer",
    "Challenge", "Order",
    "ExternalSecret", "ClusterExternalSecret", "SecretStore",
    "ClusterSecretStore", "PushSecret",
    "IngressRoute", "IngressRouteTCP", "IngressRouteUDP",
    "Middleware", "MiddlewareTCP", "TLSOption", "TLSStore",
    "TraefikService", "ServersTransport", "ServersTransportTCP",
}

KNOWN_KINDS = CORE_KINDS | CRD_KINDS

# Pipeline walker's excluded fields (matches schema_walker.EXCLUDED_FIELDS)
# Note: "selector" was removed to unblock PushSecret refs.
# Note: "kind" is excluded at depth 1 only (root envelope) but allowed at
# deeper levels for discriminator detection.
PIPELINE_EXCLUDED = frozenset({
    "status", "namespace", "apiVersion", "kind", "resourceVersion",
    "selfLink", "creationTimestamp", "deletionTimestamp",
    "deletionGracePeriodSeconds", "generation", "finalizers",
    "ownerReferences", "managedFields", "annotations", "labels",
})
PIPELINE_MAX_DEPTH = 8

# Known side-effect outputs (correctly classified as output, not input ref)
SIDE_EFFECT_OUTPUTS = {
    ("cert-manager", "Certificate", "spec.secretName"),
    ("external-secrets", "ExternalSecret", "spec.target.name"),
    ("external-secrets", "ClusterExternalSecret", "spec.externalSecretName"),
}

# Fields where the field name suggests a Kind ref but it's actually a
# SecretKeySelector (reference to a key within a Secret, not to the Kind
# in the name). The pipeline should detect these as Secret refs, not as
# the Kind implied by the field name.
SECRET_KEY_SELECTOR_OVERRIDES = {
    # vault appRole.roleRef is a SecretKeySelector for "Secret containing the role ID"
    "roleRef",
}


@dataclass
class ExpectedRef:
    service: str
    kind: str
    field_path: str
    field_name: str
    expected_target: str
    detection_method: str
    depth: int
    confidence: str
    parent_path: str = ""
    has_excluded_sibling_kind: bool = False  # True if sibling 'kind' field has enum but is excluded


@dataclass
class DetectedRef:
    kind: str
    field_path: str
    target_kind: str
    detection_source: str
    confidence: float


@dataclass
class MissingEdge:
    service: str
    kind: str
    field_path: str
    field_name: str
    expected_target: str
    detection_method: str
    depth: int
    root_cause: str
    root_cause_category: str
    suggested_detector: str
    suggested_fix: str


# ── Schema Walking (unlimited depth) ─────────────────────────────────────

def walk_schema_unlimited(
    properties: dict[str, Any],
    prefix: str = "spec",
    depth: int = 1,
    required_fields: list[str] | None = None,
    in_array: bool = False,
) -> list[dict]:
    """Recursively walk schema with NO depth limit."""
    results = []
    req = set(required_fields or [])

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue

        field_path = f"{prefix}.{prop_name}"
        field_info = {
            "path": field_path,
            "name": prop_name,
            "schema": prop_schema,
            "depth": depth,
            "in_array": in_array,
            "required": prop_name in req,
            "parent_path": prefix,
            # Include sibling info for context
            "sibling_names": set(properties.keys()),
        }
        results.append(field_info)

        # Recurse into objects
        if prop_schema.get("type") == "object" and "properties" in prop_schema:
            results.extend(walk_schema_unlimited(
                prop_schema["properties"],
                prefix=field_path,
                depth=depth + 1,
                required_fields=prop_schema.get("required", []),
                in_array=in_array,
            ))

        # Recurse into array items
        if prop_schema.get("type") == "array":
            items = prop_schema.get("items", {})
            if isinstance(items, dict) and "properties" in items:
                results.extend(walk_schema_unlimited(
                    items["properties"],
                    prefix=field_path,
                    depth=depth + 1,
                    required_fields=items.get("required", []),
                    in_array=True,
                ))

    return results


# ── Reference Detection Heuristics ───────────────────────────────────────

def is_secret_key_selector_shape(schema: dict) -> bool:
    """Check if schema is a SecretKeySelector-like shape {key, name, namespace?}."""
    if schema.get("type") != "object":
        return False
    props = schema.get("properties", {})
    return "key" in props and "name" in props


def extract_kind_from_suffix(field_name: str) -> str | None:
    """Extract target Kind from field name suffix patterns."""
    lower = field_name.lower()

    # Direct compound patterns
    if lower.endswith("secretkeyref"):
        return "Secret"
    if lower.endswith("configmapkeyref"):
        return "ConfigMap"

    # *SecretRef -> Secret
    if lower.endswith("secretref"):
        return "Secret"

    # serviceAccountRef -> ServiceAccount
    if lower.endswith("serviceaccountref"):
        return "ServiceAccount"

    # Check each known Kind as suffix + Ref/Refs
    for kind in sorted(KNOWN_KINDS, key=len, reverse=True):
        kind_lower = kind.lower()
        for suffix in ("ref", "refs"):
            pattern = kind_lower + suffix
            if lower == pattern or lower.endswith(pattern):
                idx = len(field_name) - len(pattern)
                if idx == 0 or field_name[idx - 1].islower():
                    return kind

    return None


def extract_kind_from_name_suffix(field_name: str) -> str | None:
    """Extract target from *Name patterns like secretName."""
    lower = field_name.lower()

    name_patterns = {
        "secretname": "Secret",
        "servicename": "Service",
        "serviceaccountname": "ServiceAccount",
        "ingressclassname": "IngressClass",
        "claimname": "PersistentVolumeClaim",
        "storageclassname": "StorageClass",
        "configmapname": "ConfigMap",
        "namespacename": "Namespace",
    }
    if lower in name_patterns:
        return name_patterns[lower]

    # Dynamic: {Kind}Name
    for kind in sorted(KNOWN_KINDS, key=len, reverse=True):
        kind_lower = kind.lower()
        pattern = kind_lower + "name"
        if lower.endswith(pattern):
            idx = len(field_name) - len(pattern)
            if idx == 0 or field_name[idx - 1].islower():
                return kind

    return None


def check_parent_kind_ref(
    parent_path: str, field_name: str, sibling_names: set[str],
) -> tuple[bool, str | None, bool]:
    """Check if parent path implies a Kind reference.

    Returns (is_ref, target_kind, has_excluded_kind_sibling).
    """
    if field_name != "name":
        return False, None, False

    parts = parent_path.split(".")
    if not parts:
        return False, None, False

    last_parent = parts[-1]
    for kind in KNOWN_KINDS:
        kind_lower = kind.lower()
        if last_parent.lower() == kind_lower + "s" or last_parent.lower() == kind_lower:
            # Check if there's a 'kind' sibling with enum (excluded by walker)
            has_kind_sibling = "kind" in sibling_names
            return True, kind, has_kind_sibling

    return False, None, False


def check_description_ref(description: str) -> tuple[bool, str | None]:
    """Check if description explicitly mentions a resource reference."""
    if not description:
        return False, None

    patterns = [
        r"The\s+name\s+of\s+the\s+(\w+)\s+resource\s+being\s+referred\s+to",
        r"reference\s+to\s+(?:a\s+)?(\w+)\s+resource",
        r"refers?\s+to\s+(?:a\s+)?(?:the\s+)?(\w+)\s+(?:resource|object|kind)",
    ]

    for pattern in patterns:
        m = re.search(pattern, description, re.IGNORECASE)
        if m:
            word = m.group(1)
            for kind in KNOWN_KINDS:
                if word.lower() == kind.lower():
                    return True, kind

    return False, None


# ── Step 1: Extract ALL expected references ──────────────────────────────

def extract_expected_refs(service: str, spec: dict) -> list[ExpectedRef]:
    """Walk every Kind in the spec and find all fields that should be refs."""
    results: list[ExpectedRef] = []
    schemas = spec.get("components", {}).get("schemas", {})

    for schema_name, schema_def in schemas.items():
        if not isinstance(schema_def, dict):
            continue
        if schema_name in ("ObjectMeta", "ListMeta"):
            continue

        kind = schema_name
        spec_schema = schema_def.get("properties", {}).get("spec", {})
        if not spec_schema or "properties" not in spec_schema:
            continue

        spec_properties = spec_schema.get("properties", {})
        spec_required = spec_schema.get("required", [])

        all_fields = walk_schema_unlimited(
            spec_properties, prefix="spec", depth=1,
            required_fields=spec_required,
        )

        detected_paths: set[str] = set()

        for f in all_fields:
            fname = f["name"]
            fpath = f["path"]
            fschema = f["schema"]
            fdepth = f["depth"]
            parent_path = f["parent_path"]
            sibling_names = f["sibling_names"]

            if any(fpath.startswith(dp + ".") for dp in detected_paths):
                continue

            # Method 1: Suffix pattern matching (*Ref, *SecretRef, etc.)
            target = extract_kind_from_suffix(fname)
            if target:
                # Check if this is actually a SecretKeySelector shape
                # where the field name implies a different Kind but the
                # schema is {key, name, namespace?} pointing to a Secret
                actual_target = target
                if fname in SECRET_KEY_SELECTOR_OVERRIDES and is_secret_key_selector_shape(fschema):
                    actual_target = "Secret"

                results.append(ExpectedRef(
                    service=service, kind=kind, field_path=fpath,
                    field_name=fname, expected_target=actual_target,
                    detection_method="suffix_pattern", depth=fdepth,
                    confidence="high", parent_path=parent_path,
                ))
                detected_paths.add(fpath)
                continue

            # Method 2: *Name patterns (secretName, serviceName)
            target = extract_kind_from_name_suffix(fname)
            if target:
                results.append(ExpectedRef(
                    service=service, kind=kind, field_path=fpath,
                    field_name=fname, expected_target=target,
                    detection_method="kind_name_pattern", depth=fdepth,
                    confidence="high", parent_path=parent_path,
                ))
                detected_paths.add(fpath)
                continue

            # Method 3: SecretKeySelector shape {key, name, namespace?}
            # where field name contains "secret" or ends with "Ref"
            if is_secret_key_selector_shape(fschema):
                lower = fname.lower()
                is_secret_ref = (
                    "secret" in lower
                    or lower.endswith("ref")
                    or lower.endswith("refs")
                )
                if is_secret_ref:
                    results.append(ExpectedRef(
                        service=service, kind=kind, field_path=fpath,
                        field_name=fname, expected_target="Secret",
                        detection_method="secret_key_selector", depth=fdepth,
                        confidence="high", parent_path=parent_path,
                    ))
                    detected_paths.add(fpath)
                    continue

            # Method 4: Ref tuple shape {name, namespace?, kind?, apiGroup?}
            # (but NOT SecretKeySelector shapes which are handled above)
            if fschema.get("type") == "object":
                props = fschema.get("properties", {})
                if "name" in props and isinstance(props.get("name", {}), dict):
                    if props.get("name", {}).get("type") == "string":
                        ref_indicators = {"namespace", "kind", "apiGroup", "apiVersion", "group"}
                        has_indicator = any(ind in props for ind in ref_indicators)
                        has_strong = "kind" in props or "apiGroup" in props or "apiVersion" in props
                        if has_indicator and has_strong:
                            # Resolve from kind enum
                            tuple_target = None
                            kind_prop = props.get("kind", {})
                            if isinstance(kind_prop, dict):
                                kind_enum = kind_prop.get("enum", [])
                                for val in kind_enum:
                                    if isinstance(val, str) and val in KNOWN_KINDS:
                                        tuple_target = val
                                        break
                            target_str = tuple_target or "UNKNOWN_KIND"
                            results.append(ExpectedRef(
                                service=service, kind=kind, field_path=fpath,
                                field_name=fname, expected_target=target_str,
                                detection_method="ref_tuple", depth=fdepth,
                                confidence="high" if tuple_target else "medium",
                                parent_path=parent_path,
                            ))
                            detected_paths.add(fpath)
                            continue

            # Method 5: Parent-kind-name (middlewares[].name -> Middleware)
            is_parent_ref, parent_target, has_excluded_kind = check_parent_kind_ref(
                parent_path, fname, sibling_names,
            )
            if is_parent_ref and parent_target:
                results.append(ExpectedRef(
                    service=service, kind=kind, field_path=fpath,
                    field_name=fname, expected_target=parent_target,
                    detection_method="parent_kind_name", depth=fdepth,
                    confidence="high", parent_path=parent_path,
                    has_excluded_sibling_kind=has_excluded_kind,
                ))
                detected_paths.add(fpath)
                continue

            # Method 6: Description-based (string fields with strong descriptions)
            if fschema.get("type") == "string":
                desc = fschema.get("description", "")
                is_desc_ref, desc_target = check_description_ref(desc)
                if is_desc_ref and desc_target:
                    results.append(ExpectedRef(
                        service=service, kind=kind, field_path=fpath,
                        field_name=fname, expected_target=desc_target,
                        detection_method="description_ref", depth=fdepth,
                        confidence="medium", parent_path=parent_path,
                    ))
                    detected_paths.add(fpath)
                    continue

    return results


# ── Step 2: Load detected refs ───────────────────────────────────────────

def load_detected_refs() -> dict[str, list[DetectedRef]]:
    """Load all refs from catalog/skills/crd/ directories (deduped)."""
    detected: dict[str, list[DetectedRef]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()

    for ref_file in SKILLS_DIR.rglob("refs/*.json"):
        try:
            data = json.loads(ref_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        parts = ref_file.parts
        refs_idx = parts.index("refs")
        kind = parts[refs_idx - 1]
        field_path = data.get("field_path", "")

        key = (kind, field_path)
        if key in seen:
            continue
        seen.add(key)

        detected[kind].append(DetectedRef(
            kind=kind,
            field_path=field_path,
            target_kind=data.get("target_kind", ""),
            detection_source=data.get("detection_source", ""),
            confidence=data.get("confidence", 0.0),
        ))

    return detected


# ── Step 3: Root Cause Analysis ──────────────────────────────────────────

def determine_root_cause(ref: ExpectedRef) -> tuple[str, str, str, str]:
    """Determine why an expected reference was missed."""
    fname = ref.field_name
    fpath = ref.field_path
    depth = ref.depth
    method = ref.detection_method

    # Check depth limit first
    if depth > PIPELINE_MAX_DEPTH:
        return (
            f"Field at depth {depth} > max_depth {PIPELINE_MAX_DEPTH}",
            "DEPTH_LIMIT",
            "schema_walker",
            f"Increase max_depth to >= {depth} or add targeted deep-walk",
        )

    # Check EXCLUDED_FIELDS
    path_parts = fpath.split(".")
    for i, part in enumerate(path_parts[1:], 1):
        if part in PIPELINE_EXCLUDED and part != fname:
            # 'kind' is only excluded at depth 1 (root level), allowed at depth > 1
            if part == "kind" and i > 1:
                continue
            return (
                f"Ancestor '{part}' in EXCLUDED_FIELDS blocks traversal to '{fpath}'",
                "EXCLUDED_ANCESTOR",
                "schema_walker",
                f"Add context-aware exception for '{part}' when it contains ref children",
            )
    if fname in PIPELINE_EXCLUDED:
        # 'kind' is only excluded at depth 1 (root level)
        if fname == "kind" and depth > 1:
            pass  # Not actually excluded
        else:
            return (
                f"Field name '{fname}' is in EXCLUDED_FIELDS",
                "EXCLUDED_FIELD_SELF",
                "schema_walker",
                f"Remove '{fname}' from EXCLUDED_FIELDS or add per-context exception",
            )

    # Method-specific analysis
    if method == "suffix_pattern":
        # Check if KindRegistry would match
        # The *Ref and *Name suffix matching is the primary detection path
        return (
            f"detect_ref should match '{fname}' via KindRegistry suffix; "
            f"may be parent-child dedup or walker not reaching field",
            "DETECTOR_MISS",
            "ref_detector:detect_ref",
            "Debug why detect_ref doesn't emit for this field",
        )

    if method == "kind_name_pattern":
        if (ref.service, ref.kind, fpath) in SIDE_EFFECT_OUTPUTS:
            return (
                f"Correctly classified as output by side-effect dict",
                "CORRECTLY_OUTPUT",
                "N/A",
                "No fix needed",
            )
        return (
            f"*Name pattern '{fname}' should be matched by KindRegistry",
            "DETECTOR_MISS",
            "ref_detector:detect_ref",
            "Debug KindRegistry is_ref_field for this pattern",
        )

    if method == "secret_key_selector":
        desc = ref.field_name.lower()
        # SecretKeySelector shapes {key, name, namespace?} that reference Secrets
        # The field name often doesn't end with *SecretRef
        return (
            f"SecretKeySelector shape at '{fpath}' (field '{fname}') not detected; "
            f"field name doesn't match *SecretRef pattern for KindRegistry",
            "SECRET_KEY_SELECTOR_MISSED",
            "ref_detector",
            "Add detector for {key, name, namespace?} shape -> Secret ref "
            "(SecretKeySelector pattern), even when field name lacks 'Secret'",
        )

    if method == "ref_tuple":
        if ref.expected_target == "UNKNOWN_KIND":
            return (
                f"Ref tuple at '{fpath}' has unresolvable target Kind",
                "REF_TUPLE_UNRESOLVABLE",
                "ref_detector:ref_tuple",
                "Kind enum absent or not in registry; "
                "needs description-based or context-aware resolution",
            )
        return (
            f"Ref tuple at '{fpath}' with target {ref.expected_target} missed",
            "REF_TUPLE_MISSED",
            "ref_detector:ref_tuple",
            "Check ref_tuple detector for this specific schema shape",
        )

    if method == "parent_kind_name":
        if ref.has_excluded_sibling_kind:
            # The parent has items with a 'kind' field (enum) but 'kind' is excluded
            return (
                f"Parent '{ref.parent_path.split('.')[-1]}' has items with 'kind' enum "
                f"but 'kind' is in EXCLUDED_FIELDS; enum_kind detector never sees it",
                "EXCLUDED_KIND_SIBLING",
                "schema_walker + ref_detector:enum_kind",
                "Either (1) exempt 'kind' from EXCLUDED_FIELDS inside array items, or "
                "(2) add parent-name-implies-Kind detector for array items",
            )
        return (
            f"Parent path implies Kind ref ('{ref.parent_path.split('.')[-1]}' -> "
            f"{ref.expected_target}) but no detector handles this pattern",
            "MISSING_PARENT_KIND_DETECTOR",
            "ref_detector",
            "Add detector: infer Kind from parent field name "
            f"(e.g., {ref.parent_path.split('.')[-1]}[].name -> {ref.expected_target})",
        )

    if method == "description_ref":
        return (
            f"Description mentions '{ref.expected_target}' reference but "
            f"field name '{fname}' doesn't trigger structural detectors",
            "DESCRIPTION_ONLY_REF",
            "ref_detector",
            "NLP detector may catch at 0.6 confidence; enhance or add alias",
        )

    return (
        f"Unknown detection gap: method={method}",
        "UNKNOWN",
        "unknown",
        "Manual investigation needed",
    )


# ── Main ──────────────────────────────────────────────────────────────────

def run_audit():
    all_expected: list[ExpectedRef] = []
    for service, spec_path in SPECS.items():
        print(f"Loading spec: {spec_path.name} ...", file=sys.stderr)
        spec = json.loads(spec_path.read_text())
        refs = extract_expected_refs(service, spec)
        kinds = sorted(set(r.kind for r in refs))
        print(f"  {service}: {len(refs)} refs across {len(kinds)} Kinds: {kinds}", file=sys.stderr)
        all_expected.extend(refs)

    # Deduplicate
    by_key: dict[tuple[str, str], ExpectedRef] = {}
    rank = {"high": 3, "medium": 2, "low": 1}
    for r in all_expected:
        key = (r.kind, r.field_path)
        existing = by_key.get(key)
        if existing is None or rank.get(r.confidence, 0) > rank.get(existing.confidence, 0):
            by_key[key] = r
    all_expected = list(by_key.values())
    print(f"\nTotal expected refs (deduplicated): {len(all_expected)}", file=sys.stderr)

    detected = load_detected_refs()
    total_det = sum(len(v) for v in detected.values())
    print(f"Total detected refs: {total_det}", file=sys.stderr)

    detected_set: set[tuple[str, str]] = set()
    for kind, refs in detected.items():
        for ref in refs:
            detected_set.add((kind, ref.field_path))

    missing: list[MissingEdge] = []
    matched_count = 0

    for ref in all_expected:
        key = (ref.kind, ref.field_path)
        if key in detected_set:
            matched_count += 1
            continue
        if (ref.service, ref.kind, ref.field_path) in SIDE_EFFECT_OUTPUTS:
            matched_count += 1
            continue

        root_cause, category, detector, fix = determine_root_cause(ref)
        missing.append(MissingEdge(
            service=ref.service, kind=ref.kind,
            field_path=ref.field_path, field_name=ref.field_name,
            expected_target=ref.expected_target,
            detection_method=ref.detection_method, depth=ref.depth,
            root_cause=root_cause, root_cause_category=category,
            suggested_detector=detector, suggested_fix=fix,
        ))

    print(f"Matched: {matched_count}, Missing: {len(missing)}", file=sys.stderr)
    return all_expected, detected, missing


def generate_report(expected, detected, missing) -> str:
    lines = []
    lines.append("# CRD Edge Detection Audit Report")
    lines.append("")
    lines.append("Generated by `platform-tools/idi/scripts/edge_detection_audit.py`")
    lines.append("")

    # ── 1. Summary ──
    lines.append("## 1. Summary")
    lines.append("")

    total_detected = sum(len(v) for v in detected.values())
    services = sorted(set(r.service for r in expected))

    lines.append("| Service | Kinds | Expected Refs | Detected | Missing | Rate |")
    lines.append("|---------|:---:|:---:|:---:|:---:|:---:|")

    for svc in services:
        svc_expected = [r for r in expected if r.service == svc]
        svc_missing = [m for m in missing if m.service == svc]
        svc_kinds = len(set(r.kind for r in svc_expected))
        svc_matched = len(svc_expected) - len(svc_missing)
        rate = (svc_matched / len(svc_expected) * 100) if svc_expected else 0
        lines.append(f"| {svc} | {svc_kinds} | {len(svc_expected)} | {svc_matched} | {len(svc_missing)} | {rate:.1f}% |")

    total_matched = len(expected) - len(missing)
    total_rate = (total_matched / len(expected) * 100) if expected else 0
    total_kinds = len(set(r.kind for r in expected))
    lines.append(f"| **TOTAL** | **{total_kinds}** | **{len(expected)}** | **{total_matched}** | **{len(missing)}** | **{total_rate:.1f}%** |")
    lines.append("")

    # ── 2. Root Cause Categories ──
    lines.append("## 2. Root Cause Categories")
    lines.append("")

    categories: dict[str, list[MissingEdge]] = defaultdict(list)
    for m in missing:
        categories[m.root_cause_category].append(m)

    cat_desc = {
        "DEPTH_LIMIT": "Field depth exceeds schema_walker max_depth (5)",
        "EXCLUDED_ANCESTOR": "An ancestor field is in EXCLUDED_FIELDS, blocking walker traversal",
        "EXCLUDED_FIELD_SELF": "The ref field itself is in EXCLUDED_FIELDS",
        "EXCLUDED_KIND_SIBLING": "Sibling 'kind' field has enum values but is excluded from walking",
        "MISSING_PARENT_KIND_DETECTOR": "Parent field name implies Kind ref but no detector handles it",
        "SECRET_KEY_SELECTOR_MISSED": "SecretKeySelector {key, name, namespace?} shape not detected as Secret ref",
        "REF_TUPLE_UNRESOLVABLE": "Reference tuple found but target Kind cannot be resolved",
        "REF_TUPLE_MISSED": "Reference tuple not detected",
        "DESCRIPTION_ONLY_REF": "Only description text indicates reference",
        "DETECTOR_MISS": "Existing detector should catch this but doesn't",
        "CORRECTLY_OUTPUT": "Correctly classified as output (not a gap)",
        "UNKNOWN": "Unknown root cause",
    }

    lines.append("| Category | Count | % of Missing | Description |")
    lines.append("|----------|:---:|:---:|-------------|")

    for cat in sorted(categories.keys(), key=lambda c: len(categories[c]), reverse=True):
        count = len(categories[cat])
        pct = (count / len(missing) * 100) if missing else 0
        desc = cat_desc.get(cat, "")
        lines.append(f"| `{cat}` | {count} | {pct:.1f}% | {desc} |")

    lines.append("")

    # ── 3. Missing Edges by Service ──
    lines.append("## 3. Missing Edges by Service and Kind")
    lines.append("")

    for svc in services:
        svc_missing = [m for m in missing if m.service == svc]
        if not svc_missing:
            lines.append(f"### {svc}: No missing edges")
            lines.append("")
            continue

        lines.append(f"### {svc} ({len(svc_missing)} missing)")
        lines.append("")

        by_kind: dict[str, list[MissingEdge]] = defaultdict(list)
        for m in svc_missing:
            by_kind[m.kind].append(m)

        for kind in sorted(by_kind.keys()):
            edges = by_kind[kind]
            lines.append(f"#### {kind} ({len(edges)} missing)")
            lines.append("")
            lines.append("| # | Field Path | Target | Depth | Method | Root Cause |")
            lines.append("|:---:|------------|--------|:---:|--------|------------|")

            for i, e in enumerate(sorted(edges, key=lambda x: x.field_path), 1):
                lines.append(
                    f"| {i} | `{e.field_path}` | {e.expected_target} "
                    f"| {e.depth} | {e.detection_method} | `{e.root_cause_category}` |"
                )
            lines.append("")

    # ── 4. Root Cause Details ──
    lines.append("## 4. Root Cause Analysis with Fixes")
    lines.append("")

    for cat in sorted(categories.keys(), key=lambda c: len(categories[c]), reverse=True):
        edges = categories[cat]
        lines.append(f"### `{cat}` ({len(edges)} edges)")
        lines.append("")
        lines.append(f"**Description:** {cat_desc.get(cat, 'N/A')}")
        lines.append("")

        # Unique root causes with examples
        by_cause: dict[str, list[MissingEdge]] = defaultdict(list)
        for e in edges:
            by_cause[e.root_cause].append(e)

        for cause, cause_edges in sorted(by_cause.items(), key=lambda x: len(x[1]), reverse=True):
            lines.append(f"**Cause:** {cause}")
            lines.append("")
            lines.append(f"**Fix:** {cause_edges[0].suggested_fix}")
            lines.append("")
            lines.append("Examples:")
            lines.append("")
            for e in cause_edges[:5]:
                lines.append(f"- `{e.kind}/{e.field_path}` -> {e.expected_target} (depth {e.depth})")
            if len(cause_edges) > 5:
                lines.append(f"- ... and {len(cause_edges) - 5} more")
            lines.append("")

    # ── 5. Prioritized Fix List ──
    lines.append("## 5. Prioritized Fix List")
    lines.append("")

    fix_items: list[tuple[int, str, str, str]] = []
    for cat, edges in sorted(categories.items(), key=lambda x: len(x[1]), reverse=True):
        impact = len(edges)
        if cat == "DEPTH_LIMIT":
            effort, action = "Low", "Change `max_depth=5` to `max_depth=8` in schema_walker.py"
        elif cat in ("EXCLUDED_ANCESTOR", "EXCLUDED_FIELD_SELF"):
            effort, action = "Low", "Remove 'selector' from EXCLUDED_FIELDS or add context-aware bypass"
        elif cat == "EXCLUDED_KIND_SIBLING":
            effort, action = "Medium", (
                "Option A: Exempt 'kind' from EXCLUDED_FIELDS inside array items. "
                "Option B: Add detect_array_item_ref that reads sibling 'kind' enum from parent schema"
            )
        elif cat == "MISSING_PARENT_KIND_DETECTOR":
            effort, action = "Medium", (
                "Add detect_parent_kind_name: when walking array item `name` field, "
                "check if parent array name matches a registered Kind plural"
            )
        elif cat == "SECRET_KEY_SELECTOR_MISSED":
            effort, action = "Low", (
                "Enhance detect_ref_tuple to match {key, name, namespace?} shape "
                "as Secret ref (SecretKeySelector pattern)"
            )
        elif cat == "REF_TUPLE_UNRESOLVABLE":
            effort, action = "Medium", (
                "External-secrets generatorRef targets custom generator CRDs; "
                "needs either registry expansion or description-based Kind inference"
            )
        elif cat == "DESCRIPTION_ONLY_REF":
            effort, action = "High", "Enhance NLP description detector with higher-confidence patterns"
        else:
            effort, action = "Medium", "See category details above"

        fix_items.append((impact, cat, effort, action))

    lines.append("| Priority | Category | Impact | Effort | Action |")
    lines.append("|:---:|----------|:---:|--------|--------|")

    for i, (impact, cat, effort, action) in enumerate(fix_items, 1):
        lines.append(f"| {i} | `{cat}` | {impact} edges | {effort} | {action} |")

    lines.append("")

    # ── 6. Detection Statistics ──
    lines.append("## 6. Detection Pipeline Statistics")
    lines.append("")

    source_counts: dict[str, int] = defaultdict(int)
    for kind_refs in detected.values():
        for ref in kind_refs:
            source_counts[ref.detection_source] += 1

    if source_counts:
        lines.append("### Edges by detection source")
        lines.append("")
        lines.append("| Detection Source | Count | % |")
        lines.append("|-----------------|:---:|:---:|")
        for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total_detected * 100) if total_detected else 0
            lines.append(f"| `{source}` | {count} | {pct:.1f}% |")
        lines.append("")

    # Depth distribution
    lines.append("### Depth distribution of expected references")
    lines.append("")
    depth_exp: dict[int, int] = defaultdict(int)
    depth_miss: dict[int, int] = defaultdict(int)
    for r in expected:
        depth_exp[r.depth] += 1
    for m in missing:
        depth_miss[m.depth] += 1

    lines.append("| Depth | Expected | Missing | Coverage |")
    lines.append("|:---:|:---:|:---:|:---:|")
    for d in sorted(set(list(depth_exp.keys()) + list(depth_miss.keys()))):
        exp = depth_exp.get(d, 0)
        mis = depth_miss.get(d, 0)
        cov = ((exp - mis) / exp * 100) if exp else 0
        tag = " **<-- pipeline max_depth**" if d == PIPELINE_MAX_DEPTH else ""
        beyond = " (beyond limit)" if d > PIPELINE_MAX_DEPTH else ""
        lines.append(f"| {d}{tag}{beyond} | {exp} | {mis} | {cov:.1f}% |")

    lines.append("")

    # ── 7. Key Architectural Insights ──
    lines.append("## 7. Key Architectural Insights")
    lines.append("")
    lines.append("### The Three Systemic Gaps")
    lines.append("")
    lines.append("1. **`kind` in EXCLUDED_FIELDS** (Traefik impact): The walker excludes `kind` at every")
    lines.append("   level to avoid confusion with the K8s envelope `kind` field. But inside array items")
    lines.append("   like `routes[].services[]`, the `kind` field carries a discriminator enum")
    lines.append("   (`[\"Service\", \"TraefikService\"]`). The `detect_enum_kind` detector never sees it.")
    lines.append("   Fix: exempt `kind` from exclusion when it's inside array items at depth > 1,")
    lines.append("   or read sibling schemas from the parent without requiring the walker to yield them.")
    lines.append("")
    lines.append("2. **`selector` in EXCLUDED_FIELDS** (PushSecret impact): PushSecret.spec.selector")
    lines.append("   contains `secret.name` (ref to Secret) and `generatorRef` (ref to generator).")
    lines.append("   Both are blocked because `selector` is excluded.")
    lines.append("   Fix: remove `selector` from EXCLUDED_FIELDS or add depth/context awareness.")
    lines.append("")
    lines.append("3. **max_depth=5 vs. provider schemas** (SecretStore/ClusterSecretStore impact):")
    lines.append("   Provider auth chains in external-secrets regularly nest to depth 6-7.")
    lines.append("   The walker stops at depth 5, missing serviceAccountRef and other refs.")
    lines.append("   Fix: increase max_depth to 7 or 8 (low risk, ~20% more fields walked).")
    lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 60, file=sys.stderr)
    print("CRD Edge Detection Audit", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    expected, detected, missing = run_audit()
    report = generate_report(expected, detected, missing)

    output_dir = ROOT / "docs" / "plans" / "impl"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "edge-detection-audit.md"
    output_path.write_text(report)
    print(f"\nReport written to: {output_path}", file=sys.stderr)
    print(report)


if __name__ == "__main__":
    main()
