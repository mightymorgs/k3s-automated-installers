"""Constants and heuristic classifier for the Helm extractor.

The heuristic classifier is the Tier E (lowest confidence) fallback,
only consulted when Tiers A-D produce no shape classification.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Binding maps (used by classifier Tier C.9)
# ---------------------------------------------------------------------------

EXISTING_BINDING_MAP: dict[str, tuple[str, str]] = {
    "secret": ("secret_binding", "Secret"),
    "secretname": ("secret_binding", "Secret"),
    "claim": ("pvc_binding", "PersistentVolumeClaim"),
    "pvc": ("pvc_binding", "PersistentVolumeClaim"),
    "configmap": ("configmap_binding", "ConfigMap"),
    "configmapname": ("configmap_binding", "ConfigMap"),
    "role": ("role_binding", "Role"),
    "serviceaccount": ("serviceaccount_binding", "ServiceAccount"),
}

# ---------------------------------------------------------------------------
# Credential leaf keys (used by classifier Tier C.3)
# ---------------------------------------------------------------------------

CREDENTIAL_LEAF_KEYS = frozenset({
    "password",
    "token",
    "apikey",
    "apiKey",
    "secretKey",
    "key",
    "clientSecret",
    "clientId",
    "secret",
    "privateKey",
    "passphrase",
    "accessKey",
    "secretAccessKey",
})

# ---------------------------------------------------------------------------
# Toggle key names (used by classifier Tier C.8)
# ---------------------------------------------------------------------------

TOGGLE_KEYS = frozenset({
    "enabled",
    "create",
    "install",
    "use",
    "manage",
    "deploy",
})

# ---------------------------------------------------------------------------
# Heuristic keyword classifier (Tier E — lowest confidence fallback)
# ---------------------------------------------------------------------------

# P1 Identity suffixes (case-insensitive)
_IDENTITY_SUFFIXES = ("name", "ref", "id", "selector")

# P2 Addressability keywords (case-insensitive substring)
_ADDRESSABILITY_KEYWORDS = frozenset({
    "host", "port", "url", "endpoint", "address", "domain", "fqdn",
})

# P3 Credential keywords (case-insensitive substring)
_CREDENTIAL_KEYWORDS = frozenset({
    "password", "secret", "token", "key", "cert", "credential", "apikey",
})

# P3 guard: these match identity suffixes but are actually identity, not credential
_CREDENTIAL_EXCLUSIONS = frozenset({
    "secretname",
})


def heuristic_classify_shape(leaf_key: str, default_value: Any) -> str:
    """Classify shape using keyword heuristics (lowest confidence tier).

    Returns one of: "identity", "addressability", "credential", "config".

    Priority: P3 Credential > P2 Addressability > P1 Identity > P5 Config.
    Credential is checked first because keys like "apiKey" should be
    credential (matching "key" substring) not identity (matching "Key" suffix).
    """
    lower = leaf_key.lower()

    # P3 Credential (checked first — "apiKey" is credential, not identity)
    if lower not in _CREDENTIAL_EXCLUSIONS:
        for kw in _CREDENTIAL_KEYWORDS:
            if kw in lower:
                return "credential"

    # P2 Addressability
    for kw in _ADDRESSABILITY_KEYWORDS:
        if kw in lower:
            return "addressability"

    # P1 Identity (suffix match)
    if lower not in _CREDENTIAL_EXCLUSIONS:
        for suffix in _IDENTITY_SUFFIXES:
            if lower.endswith(suffix):
                return "identity"

    # Special case: secretName is identity (excluded from credential above)
    if lower in _CREDENTIAL_EXCLUSIONS:
        return "identity"

    # P5 Default
    return "config"
