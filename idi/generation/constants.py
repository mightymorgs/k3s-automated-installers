"""Shared constants for the skill generation pipeline.

All constants that were previously scattered across AtomicSkillGenerator
class attributes and module-level globals are consolidated here.
"""

import re
from typing import Dict, FrozenSet, List, Optional, Set


# Generator version — increment when making breaking changes to skill format.
GENERATOR_VERSION: str = "2.4.0"

# Regex for validating service/resource names in skill JSON output.
VALID_NAME_RE: re.Pattern = re.compile(r"^[a-z0-9_-]+$")

# ── HTTP method → operation type mapping ──────────────────────────────

OPERATION_MAP: Dict[str, str] = {
    "get": "retrieve",
    "post": "create",
    "put": "replace",
    "patch": "update",
    "delete": "delete",
}

# ── Field exclusion sets ──────────────────────────────────────────────

# Fields that should never create DEPENDS_ON edges via field_refs.
# K8s namespaces are pre-existing resources, not things you create.
EXCLUDED_FIELD_REFS: FrozenSet[str] = frozenset({
    "namespace",
    "namespaces",
    "ns",
})

# ── REST action suffixes ──────────────────────────────────────────────

# Sub-path segments that represent actions on a resource, not resources
# themselves.  When these appear at the end of a path, they are stripped
# to find the actual resource, and used to refine the operation type.
REST_ACTION_SUFFIXES: Set[str] = {
    "check_access", "used_by", "health", "state", "export", "import",
    "cache_clear", "cache_info", "metadata", "default_settings",
    "add_user", "remove_user", "set_password", "set_password_flow",
    "types", "preview", "enrollment_status", "import_device_manual",
    "import_devices_automatic", "create_admin_group", "create_recovery_key",
    "object", "status", "view_key", "check_in", "mdm_config",
    "enroll", "auth_fed", "auth_ia", "agent_config", "connect_user",
    "sync", "assign", "unassign", "device", "user", "register",
    "preview_user",
}

# ── Semantic field targets ────────────────────────────────────────────

# Map field patterns to allowed target resources.
# Used to filter polymorphic resolution to semantically valid options.
SEMANTIC_FIELD_TARGETS: Dict[str, Dict[str, List[str]]] = {
    "authentik": {
        "authentication_flow": ["flows-instances"],
        "authorization_flow": ["flows-instances"],
        "invalidation_flow": ["flows-instances"],
        "configure_flow": ["flows-instances"],
        "enrollment_flow": ["flows-instances"],
        "pre_authentication_flow": ["flows-instances"],
        "target_flow": ["flows-instances"],
        "passwordless_flow": ["flows-instances"],
        "recovery_flow": ["flows-instances"],
        "flow_user_settings": ["flows-instances"],
        "flow_recovery": ["flows-instances"],
        "flow": ["flows-instances"],
    },
    "tailscale": {
        "tailnet": [],   # Account-level identifier, not created via API
    },
    "cloudflare": {
        "account_id": [],  # Account-level identifier, not created via API
    },
}

# ── Polymorphic field patterns ────────────────────────────────────────

# Define which resources are valid for polymorphic fields.
# Uses ``exclude`` sets to reject known invalid resources, and/or
# ``prefix`` for compound names.
POLYMORPHIC_FIELD_PATTERNS: Dict[str, Dict[str, Dict[str, object]]] = {
    "authentik": {
        "provider": {
            "exclude": {"scope", "ssf", "core-applications", "applications"},
            "prefix": "providers-",
        },
        "backchannel_providers": {
            "exclude": {"scope", "ssf", "core-applications", "applications"},
            "prefix": "providers-",
        },
    },
}

# ── Kubernetes wait strategies ────────────────────────────────────────

K8S_WAIT_STRATEGIES: Dict[str, Dict[str, object]] = {
    "Deployment": {
        "strategy": "condition",
        "condition": "Available",
        "timeout": 300,
    },
    "StatefulSet": {
        "strategy": "rollout_status",
        "timeout": 600,
    },
    "DaemonSet": {
        "strategy": "rollout_status",
        "timeout": 300,
    },
    "Job": {
        "strategy": "condition",
        "condition": "Complete",
        "timeout": 600,
    },
    "Pod": {
        "strategy": "condition",
        "condition": "Ready",
        "timeout": 300,
    },
    "Service": {
        "strategy": "none",
        "timeout": 0,
    },
    "ConfigMap": {
        "strategy": "none",
        "timeout": 0,
    },
    "Secret": {
        "strategy": "none",
        "timeout": 0,
    },
    "Ingress": {
        "strategy": "field",
        "field": "status.loadBalancer.ingress",
        "timeout": 120,
    },
    "PersistentVolumeClaim": {
        "strategy": "condition",
        "condition": "Bound",
        "timeout": 300,
    },
}


def filter_polymorphic_targets(
    service: str,
    field: str,
    candidates: List[str],
) -> List[str]:
    """Filter candidate resources for polymorphic field resolution.

    Excludes semantically invalid options from polymorphic resolution.
    For example, authentik ``provider`` field should only resolve to
    resources starting with ``providers-``, excluding unrelated resources
    like ``scope``.

    Args:
        service: Service name (e.g., ``'authentik'``).
        field: Field name (e.g., ``'provider'``).
        candidates: All matching resource names.

    Returns:
        Filtered list of semantically valid resource names.
    """
    service_patterns = POLYMORPHIC_FIELD_PATTERNS.get(service, {})
    field_pattern = service_patterns.get(field)
    if not field_pattern:
        return candidates

    exclude_set: set = field_pattern.get("exclude", set())
    prefix: Optional[str] = field_pattern.get("prefix")

    filtered: List[str] = []
    for c in candidates:
        if c in exclude_set:
            continue
        if prefix:
            if c.startswith(prefix) or "-" not in c:
                filtered.append(c)
        else:
            filtered.append(c)
    return filtered


def get_valid_targets_for_field(
    service: str,
    field: str,
) -> Optional[List[str]]:
    """Get allowed target resources for a field, or ``None`` if unrestricted.

    Args:
        service: Service name (e.g., ``'authentik'``).
        field: Field name (e.g., ``'authentication_flow'``).

    Returns:
        List of allowed resource names, or ``None`` if no restriction.
    """
    service_rules = SEMANTIC_FIELD_TARGETS.get(service, {})
    return service_rules.get(field)
