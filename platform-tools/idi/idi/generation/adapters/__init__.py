"""Schema family adapters for FK detection and response schema extraction.

Remaining adapters after generic detection eliminates most vendor-specific code:
- OpenApiRestAdapter: Generic base (handles most APIs)
- CloudflareAdapter: Path-based resource normalization only
- VaultAdapter: Backend detection + mount parameterization only
- AwsQueryAdapter: ARN/ID prefix/PascalCase FK + action mapping only
- GitHubOpenApiAdapter: Alias resolution only
"""
from typing import Any, Dict, Optional, Set, Type

from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
from idi.generation.adapters.cloudflare import CloudflareAdapter
from idi.generation.adapters.vault import VaultAdapter
from idi.generation.adapters.aws_query import AwsQueryAdapter
from idi.generation.adapters.github_openapi import GitHubOpenApiAdapter

__all__ = [
    "OpenApiRestAdapter",
    "CloudflareAdapter",
    "VaultAdapter",
    "AwsQueryAdapter",
    "GitHubOpenApiAdapter",
    "AdapterRegistry",
    "get_adapter",
]


class AdapterRegistry:
    """Config-driven adapter dispatch."""

    _ADAPTERS: Dict[str, Type] = {
        "rest": OpenApiRestAdapter,
        "openapi": OpenApiRestAdapter,
        "cloudflare": CloudflareAdapter,
        "vault": VaultAdapter,
        "aws": AwsQueryAdapter,
        "query": AwsQueryAdapter,
        "github": GitHubOpenApiAdapter,
        "swagger": OpenApiRestAdapter,
        "swagger2": OpenApiRestAdapter,
    }

    def __init__(self) -> None:
        self._adapters: Dict[str, Type] = dict(self._ADAPTERS)

    def register(self, style: str, adapter_class: Type) -> None:
        """Register a custom adapter class."""
        self._adapters[style.lower()] = adapter_class

    def get(
        self,
        style: str,
        service: str,
        known_resources: Optional[Set[str]] = None,
        spec: Optional[Dict[str, Any]] = None,
    ):
        """Get adapter instance for given style."""
        adapter_class = self._adapters.get(style.lower())
        if not adapter_class:
            raise ValueError(f"Unknown adapter style: {style}")

        if adapter_class is CloudflareAdapter:
            return adapter_class(service=service, known_resources=known_resources, spec=spec)
        return adapter_class(service=service, known_resources=known_resources)

    def detect_style(
        self,
        sample_path: str,
        service: str = "",
        spec: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Auto-detect adapter style from service name and path patterns."""
        if service.lower() in ("vault", "hashicorp-vault"):
            return "vault"
        if service.lower() == "cloudflare":
            return "cloudflare"
        if service.lower() == "github":
            return "github"

        if spec and _is_vault_spec(spec):
            return "vault"

        if "Action=" in sample_path or "#Action=" in sample_path:
            return "aws"

        return "rest"


def _is_vault_spec(spec: Dict[str, Any]) -> bool:
    """Detect HashiCorp Vault API by path structure."""
    paths = spec.get("paths", {})
    vault_indicators = ("/sys/", "/auth/", "/secret/", "/database/", "/pki/", "/transit/")
    indicator_count = 0
    for path in paths:
        if any(ind in path for ind in vault_indicators):
            indicator_count += 1
            if indicator_count >= 3:
                return True
    return False


_registry = AdapterRegistry()


def get_adapter(
    service: str,
    style: Optional[str] = None,
    sample_path: Optional[str] = None,
    known_resources: Optional[Set[str]] = None,
    spec: Optional[Dict[str, Any]] = None,
):
    """Get appropriate adapter for a service."""
    if style is None:
        style = _registry.detect_style(sample_path or "", service=service, spec=spec)
    return _registry.get(style, service, known_resources, spec=spec)
