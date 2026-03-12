"""Operator side-effect registry — layered classification for *Name fields.

Layer 1: Description NLP (confidence 0.6) — parse field descriptions
Layer 2: Dictionary (confidence 0.95) — known operator side effects, overrides NLP
Layer 3: RBAC extraction (dep_adapters/rbac_deps.py) — auto-discovers operator
         side effects from Helm chart ClusterRole/Role permissions at runtime.

The hand-written ``OPERATOR_SIDE_EFFECTS`` dictionary in this module remains
as a high-confidence (0.95) fallback override for known ground-truth that RBAC
extraction may not discover or may misclassify.  RBAC extraction is the primary
automated discovery mechanism (Phase 4); this dictionary supplements it.
"""
from __future__ import annotations

import re

# Known operator side effects: (group, kind) -> list of side-effect dicts.
# Each entry: {field, produces_kind, produces_group}.
OPERATOR_SIDE_EFFECTS: dict[tuple[str, str], list[dict[str, str]]] = {
    ("cert-manager.io", "Certificate"): [
        {"field": "spec.secretName", "produces_kind": "Secret", "produces_group": "core"},
    ],
    ("cert-manager.io", "Issuer"): [],
    ("cert-manager.io", "ClusterIssuer"): [],
    ("external-secrets.io", "ExternalSecret"): [
        {"field": "spec.target.name", "produces_kind": "Secret", "produces_group": "core"},
    ],
    ("external-secrets.io", "PushSecret"): [
        {"field": "spec.data[].remoteRef.remoteKey", "produces_kind": "kv", "produces_group": "vault"},
    ],
    ("external-secrets.io", "ClusterExternalSecret"): [
        {"field": "spec.externalSecretName", "produces_kind": "ExternalSecret", "produces_group": "external-secrets.io"},
    ],
    ("traefik.io", "IngressRoute"): [],
    ("traefik.io", "Middleware"): [],
    ("monitoring.coreos.com", "ServiceMonitor"): [],
    ("monitoring.coreos.com", "PodMonitor"): [],
    ("monitoring.coreos.com", "PrometheusRule"): [],
    ("longhorn.io", "Volume"): [],
    ("longhorn.io", "BackingImage"): [],
}

# NLP patterns for description-based classification.
_OUTPUT_PATTERNS = re.compile(
    r"will be (?:automatically )?created|"
    r"will be generated|"
    r"managed by this|"
    r"populated with|"
    r"output (?:secret|resource)",
    re.IGNORECASE,
)

_INPUT_PATTERNS = re.compile(
    r"must exist|"
    r"reference to|"
    r"name of (?:the |an )?existing|"
    r"refers to|"
    r"should already exist",
    re.IGNORECASE,
)


def get_side_effects(group: str, kind: str) -> list[dict[str, str]]:
    """Look up known side effects for a CRD kind."""
    return OPERATOR_SIDE_EFFECTS.get((group, kind), [])


def is_output_by_description(description: str) -> bool | None:
    """Check if a field description suggests output vs input.

    Returns:
        True if output, False if input, None if ambiguous.
    """
    if not description:
        return None
    if _OUTPUT_PATTERNS.search(description):
        return True
    if _INPUT_PATTERNS.search(description):
        return False
    return None


def classify_name_field(
    field_path: str,
    group: str,
    kind: str,
    description: str = "",
) -> tuple[str, float]:
    """Classify a *Name field as input_ref, output_declaration, or config_field.

    Uses layered confidence: dictionary (0.95) overrides NLP (0.6).

    Returns:
        Tuple of (role, confidence).
    """
    # Layer 2: Dictionary lookup (highest confidence).
    effects = get_side_effects(group, kind)
    for effect in effects:
        if effect["field"] == field_path:
            return "output_declaration", 0.95

    # Layer 1: Description NLP (lower confidence).
    nlp_result = is_output_by_description(description)
    if nlp_result is True:
        return "output_declaration", 0.6
    if nlp_result is False:
        return "input_ref", 0.6

    # Default: treat as config field.
    return "config_field", 0.5
