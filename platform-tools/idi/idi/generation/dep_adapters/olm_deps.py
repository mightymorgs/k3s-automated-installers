"""OLM dependency adapter — translates OLM CSV required GVKs into Dependencies.

Parses OLM ClusterServiceVersion data from OperatorHub.io to extract
explicitly declared CRD dependencies (ground-truth metadata).  Registers
``owned`` GVKs in the KindRegistry for other detectors.

Priority: 95 (highest — ground-truth from operator author).
No import-time side effects.
"""
from __future__ import annotations

import logging
from typing import Any

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import GVKRef, extract_gvk_dependencies, fetch_olm_csv
from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output

logger = logging.getLogger(__name__)


class OlmDepAdapter:
    """Detects K8s CRD dependencies from OLM ClusterServiceVersion metadata."""

    name = "olm_deps"
    priority = 95  # Highest — ground-truth from operator author

    def __init__(self, registry: KindRegistry | None = None) -> None:
        self.registry = registry or KindRegistry()
        self._cached: dict[str, tuple[list[Dependency], list[GVKRef]]] = {}

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        """Match specs with K8s-style API paths."""
        for path in spec.get("paths", {}):
            if "/apis/" in path or path.startswith("/api/v1/namespaces"):
                return True
        return False

    def _extract_cached(
        self, service: str,
    ) -> tuple[list[Dependency], list[GVKRef]]:
        """Fetch and parse OLM CSV with per-service caching."""
        if service in self._cached:
            return self._cached[service]

        csv = fetch_olm_csv(service)
        if csv is None:
            result: tuple[list[Dependency], list[GVKRef]] = ([], [])
            self._cached[service] = result
            return result

        owned, required = extract_gvk_dependencies(csv)

        # Register owned GVKs in KindRegistry.
        for gvk in owned:
            self.registry.register(gvk.kind, gvk.plural, group=gvk.group)
            logger.debug(
                "olm_deps:owned_register %s/%s (plural=%s)",
                gvk.group, gvk.kind, gvk.plural,
            )

        # Build Dependency objects for required GVKs.
        deps: list[Dependency] = []
        for req in required:
            plural = self.registry.kind_to_plural(req.kind)
            if plural is None:
                logger.debug(
                    "OLM required Kind %s not in KindRegistry — skipping (no naive pluralization)",
                    req.kind,
                )
                continue

            deps.append(Dependency(
                field=f"olm:required:{req.group}/{req.kind}",
                target_resource=plural,
                fact_ref=f"crdfacts://{req.group}/{req.kind}#name",
                confidence=0.95,
                source="olm_deps:required",
                lineage_type="reference",
            ))

        result = (deps, owned)
        self._cached[service] = result
        return result

    def detect_dependencies(
        self,
        operation: OperationInfo,
        spec: dict[str, Any],
        known_resources: set[str],
    ) -> list[Dependency]:
        deps, _ = self._extract_cached(operation.service)
        return deps

    def detect_outputs(
        self,
        operation: OperationInfo,
        spec: dict[str, Any],
    ) -> list[Output]:
        """OLM does not produce Output edges — side-effects handled by RBAC adapter."""
        return []
