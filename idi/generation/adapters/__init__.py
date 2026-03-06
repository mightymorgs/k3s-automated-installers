"""Schema family adapters for FK detection and response schema extraction.

Provides adapters for different API schema types:
- OpenAPI REST: Standard REST APIs
- Cloudflare: APIs with {result, success, errors, messages} wrapper
- Vault: HashiCorp Vault with backend-specific response envelopes
- Kubernetes CRD: Custom Resource Definitions
- AWS Query: AWS-style action-based APIs
- GitHub: GitHub's pseudo-OpenAPI spec
- Swagger 2.0: Legacy Swagger specs

Usage:
    from idi.generation.adapters import get_adapter

    adapter = get_adapter(service="authentik", style="rest")
    refs = adapter.extract_field_refs(schema, resource)

    # Cloudflare auto-detected or explicit:
    adapter = get_adapter(service="cloudflare", style="cloudflare")
    schema = adapter.extract_response_schema(operation, method, path)

    # Vault auto-detected or explicit:
    adapter = get_adapter(service="vault", style="vault")
    schema = adapter.extract_response_schema(operation, method, path, spec=spec)
"""
from typing import Any, Dict, Optional, Set, Type
import re

from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
from idi.generation.adapters.cloudflare import CloudflareAdapter
from idi.generation.adapters.vault import VaultAdapter
from idi.generation.adapters.kubernetes_crd import KubernetesCrdAdapter
from idi.generation.adapters.aws_query import AwsQueryAdapter
from idi.generation.adapters.swagger2 import Swagger2Adapter
from idi.generation.adapters.github_openapi import GitHubOpenApiAdapter

__all__ = [
    "OpenApiRestAdapter",
    "CloudflareAdapter",
    "VaultAdapter",
    "KubernetesCrdAdapter",
    "AwsQueryAdapter",
    "Swagger2Adapter",
    "GitHubOpenApiAdapter",
    "AdapterRegistry",
    "get_adapter",
]


class AdapterRegistry:
    """Registry for schema adapters."""

    def __init__(self):
        self._adapters: Dict[str, Type] = {
            "rest": OpenApiRestAdapter,
            "openapi": OpenApiRestAdapter,
            "cloudflare": CloudflareAdapter,
            "vault": VaultAdapter,
            "kubernetes": KubernetesCrdAdapter,
            "k8s": KubernetesCrdAdapter,
            "crd": KubernetesCrdAdapter,
            "aws": AwsQueryAdapter,
            "query": AwsQueryAdapter,
            "swagger": Swagger2Adapter,
            "swagger2": Swagger2Adapter,
            "github": GitHubOpenApiAdapter,
        }

    def register(self, style: str, adapter_class: Type) -> None:
        """Register a custom adapter class."""
        self._adapters[style.lower()] = adapter_class

    def get(self, style: str, service: str, known_resources: Optional[Set[str]] = None,
            spec: Optional[Dict[str, Any]] = None):
        """Get adapter instance for given style.

        Args:
            style: Adapter style key
            service: Service name
            known_resources: Known resource names for FK resolution
            spec: Full OpenAPI spec (passed to adapters that need $ref resolution)
        """
        adapter_class = self._adapters.get(style.lower())
        if not adapter_class:
            raise ValueError(f"Unknown adapter style: {style}")

        # CloudflareAdapter accepts an extra 'spec' kwarg for $ref resolution
        if adapter_class is CloudflareAdapter:
            return adapter_class(service=service, known_resources=known_resources, spec=spec)

        # VaultAdapter uses the standard constructor (spec is passed per-call
        # to extract_response_schema, not at init time)
        return adapter_class(service=service, known_resources=known_resources)

    def detect_style(self, sample_path: str, service: str = "",
                     spec: Optional[Dict[str, Any]] = None) -> str:
        """Auto-detect style from sample API path and/or spec structure.

        Detection order:
        1. Service name matches (highest priority - explicit naming)
        2. Spec structure detection (medium priority - API characteristics)
        3. Path pattern matching (fallback - URL conventions)

        Args:
            sample_path: Sample API path for pattern matching
            service: Service name (for name-based detection)
            spec: Full OpenAPI spec (for response structure detection)
        """
        # Priority 1: Service name matches (most reliable)
        if service.lower() in ("vault", "hashicorp-vault"):
            return "vault"
        if service.lower() == "cloudflare":
            return "cloudflare"
        # PHASE 2 FIX (A2-002): Add GitHub adapter detection
        if service.lower() == "github":
            return "github"

        # Priority 2: Spec structure detection
        # Check Vault first (more specific paths)
        if spec and _is_vault_spec(spec):
            return "vault"
        # Check Cloudflare (response wrapper pattern)
        if spec and _is_cloudflare_spec(spec):
            return "cloudflare"

        # Priority 3: Path pattern matching
        # Kubernetes: /apis/<group>/<version>/ or /api/v1/ core
        if re.match(r"^/apis/[a-z0-9.-]+/v\d+", sample_path, re.IGNORECASE):
            return "kubernetes"
        if re.match(r"^/api/v\d+/", sample_path, re.IGNORECASE):
            return "kubernetes"
        if "Action=" in sample_path or "#Action=" in sample_path:
            return "aws"
        return "rest"


def _is_vault_spec(spec: Dict[str, Any]) -> bool:
    """Detect HashiCorp Vault API by path structure.

    Vault specs have characteristic paths like ``/sys/``, ``/auth/``,
    ``/secret/data/``, etc.

    Args:
        spec: Full OpenAPI spec dict

    Returns:
        True if this looks like a Vault API spec
    """
    paths = spec.get("paths", {})
    vault_indicators = ("/sys/", "/auth/", "/secret/", "/database/", "/pki/", "/transit/")
    indicator_count = 0

    for path in paths:
        if any(ind in path for ind in vault_indicators):
            indicator_count += 1
            # If we see 3+ Vault-like paths, it's very likely Vault
            if indicator_count >= 3:
                return True

    return False


def _is_cloudflare_spec(spec: Dict[str, Any]) -> bool:
    """Detect Cloudflare API by response schema structure.

    Samples up to 5 paths looking for the characteristic
    {result, success, errors, messages} wrapper pattern.

    Args:
        spec: Full OpenAPI spec dict

    Returns:
        True if this looks like a Cloudflare API spec
    """
    paths = spec.get("paths", {})
    checked = 0

    for path, methods in paths.items():
        if checked >= 5:
            break
        if not isinstance(methods, dict):
            continue

        for method_key, operation in methods.items():
            if method_key.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            if not isinstance(operation, dict):
                continue

            responses = operation.get("responses", {})
            success = responses.get("200", {})
            if not isinstance(success, dict):
                continue

            schema = (
                success.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if not isinstance(schema, dict):
                continue

            # Check direct properties
            if _has_cloudflare_wrapper(schema):
                return True

            # Check allOf composition (common Cloudflare pattern)
            if "allOf" in schema:
                merged_props = {}
                for sub in schema["allOf"]:
                    if isinstance(sub, dict):
                        merged_props.update(sub.get("properties", {}))
                if _has_cloudflare_wrapper({"properties": merged_props}):
                    return True

            checked += 1
            break  # Only check one method per path

    return False


def _has_cloudflare_wrapper(schema: Dict[str, Any]) -> bool:
    """Check if a schema has the Cloudflare wrapper signature."""
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        return False
    # Must have at least result + success + errors (messages is optional)
    return all(k in props for k in ("result", "success", "errors"))


_registry = AdapterRegistry()


def get_adapter(
    service: str,
    style: Optional[str] = None,
    sample_path: Optional[str] = None,
    known_resources: Optional[Set[str]] = None,
    spec: Optional[Dict[str, Any]] = None,
):
    """Get appropriate adapter for a service.

    Args:
        service: Service name (e.g., 'authentik', 'ec2', 'cloudflare')
        style: Adapter style (rest, cloudflare, kubernetes, aws, github, swagger2).
               If None, auto-detects from service name, spec structure, or
               sample_path. Defaults to 'rest'.
        sample_path: Sample API path for auto-detection
        known_resources: Set of known resource names for FK resolution
        spec: Full OpenAPI spec dict (enables Cloudflare auto-detection and
              $ref resolution in adapters that need it)

    Returns:
        Adapter instance for the given style
    """
    if style is None and sample_path:
        style = _registry.detect_style(sample_path, service=service, spec=spec)
    elif style is None:
        # Try service-name or spec-based detection before defaulting to rest
        style = _registry.detect_style("", service=service, spec=spec)
    return _registry.get(style, service, known_resources, spec=spec)
