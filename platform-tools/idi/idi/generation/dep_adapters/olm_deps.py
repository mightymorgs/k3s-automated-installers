"""OLM dependency adapter — translates OLM CSV required GVKs into Dependencies.

Parses OLM ClusterServiceVersion data from OperatorHub.io to extract
explicitly declared CRD dependencies (ground-truth metadata).  Registers
``owned`` GVKs in the KindRegistry for other detectors.

Priority: 95 (highest — ground-truth from operator author).
No import-time side effects.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.olm_loader import (
    GVKRef,
    extract_alm_examples,
    extract_gvk_dependencies,
    fetch_olm_csv,
)
from idi.generation.crd.topo_sort import DependencyEdge
from idi.generation.dep_adapters.base import Dependency, DetectionSource, OperationInfo, Output

logger = logging.getLogger(__name__)

_LABEL_KEY_DENYLIST_PREFIXES: tuple[str, ...] = (
    "app.kubernetes.io/",
    "helm.sh/",
    "kubernetes.io/",
    "k8s.io/",
    "meta.helm.sh/",
    "argocd.argoproj.io/",
)

_GENERIC_VALUE_RE = re.compile(
    r"(?i)^(example|default|sample|test|my-.*"
    r"|.*-(example|sample|test)"
    r"|(example|sample|test)-.*)$"
)

_GENERIC_KEY_SEGMENTS: frozenset[str] = frozenset({
    "instance", "managed-by", "part-of", "component",
    "name", "app", "tier",
})


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
            self.registry.register(gvk.kind, gvk.plural, group=gvk.group, service=service)
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
                detection_source=DetectionSource.DEFAULT,
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
        """Emit one Output per owned GVK declared in the OLM CSV."""
        _, owned = self._extract_cached(operation.service)
        for gvk in owned:
            logger.debug(
                "olm_deps:owned_output %s/%s", gvk.group, gvk.kind,
            )
        return [
            Output(
                field=f"olm:owned:{gvk.group}/{gvk.kind}",
                fact_ref=f"crdfacts://{gvk.group}/{gvk.kind}#name",
                source="olm_deps:owned",
                priority=3,
            )
            for gvk in owned
        ]

    @staticmethod
    def _group_from_api_version(api_version: str) -> str:
        """Extract API group from apiVersion string.

        "kafka.strimzi.io/v1beta2" → "kafka.strimzi.io"
        "v1" → "" (core)
        """
        if "/" in api_version:
            return api_version.split("/", 1)[0]
        return ""

    def _extract_alm_label_edges(
        self,
        examples: list[dict],
        owned_gvks: list[GVKRef],
        registry: KindRegistry,
    ) -> list[DependencyEdge]:
        """Extract label-based parent-child edges from ALM examples.

        Applies 5 precision gates. Only edges passing ALL gates are emitted.
        Returns deduplicated list of DependencyEdge objects.
        """
        # Build name index: metadata.name → set of (apiVersion, kind)
        name_index: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            kind = ex.get("kind")
            api_version = ex.get("apiVersion", "")
            meta = ex.get("metadata")
            if not isinstance(meta, dict) or not isinstance(kind, str):
                continue
            ex_name = meta.get("name")
            if isinstance(ex_name, str):
                name_index[ex_name].add((api_version, kind))

        owned_kinds = {gvk.kind for gvk in owned_gvks}
        owned_groups = {gvk.group for gvk in owned_gvks}

        # Map kind → group from owned GVKs for edge construction
        kind_to_group: dict[str, str] = {}
        for gvk in owned_gvks:
            kind_to_group.setdefault(gvk.kind, gvk.group)

        seen: set[tuple[str, str]] = set()
        edges: list[DependencyEdge] = []

        for ex in examples:
            if not isinstance(ex, dict):
                continue
            child_kind = ex.get("kind")
            child_api_version = ex.get("apiVersion", "")
            meta = ex.get("metadata")
            if not isinstance(meta, dict) or not isinstance(child_kind, str):
                continue
            labels = meta.get("labels")
            if not isinstance(labels, dict):
                continue

            child_group = self._group_from_api_version(child_api_version)

            for label_key, label_value in labels.items():
                if not isinstance(label_value, str):
                    continue

                # Pre-filter: denylist prefixes
                if any(label_key.startswith(p) for p in _LABEL_KEY_DENYLIST_PREFIXES):
                    continue

                # Gate 2 (domain extraction): key must have "/"
                if "/" not in label_key:
                    continue
                domain, key_segment = label_key.split("/", 1)

                # Gate 4: generic key segment
                if key_segment in _GENERIC_KEY_SEGMENTS:
                    continue

                # Gate 3: generic value
                if _GENERIC_VALUE_RE.match(label_value):
                    continue

                # Gate 1: exact unique name cross-link
                matches = name_index.get(label_value)
                if not matches or len(matches) != 1:
                    continue
                parent_api_version, parent_kind = next(iter(matches))

                # Self-loop check
                if parent_kind == child_kind:
                    continue

                # Gate 2 (domain match): domain must match an owned group
                domain_match = False
                for group in owned_groups:
                    if domain == group:
                        domain_match = True
                        break
                    if group.endswith("." + domain):
                        domain_match = True
                        break
                    if domain.endswith("." + group):
                        domain_match = True
                        break
                if not domain_match:
                    continue

                # Gate 5: target Kind validation
                if parent_kind not in owned_kinds:
                    continue
                if registry.kind_to_plural(parent_kind) is None:
                    continue

                # Resolve parent group
                parent_group = kind_to_group.get(
                    parent_kind,
                    self._group_from_api_version(parent_api_version),
                )

                source_gk = f"{child_group}/{child_kind}"
                target_gk = f"{parent_group}/{parent_kind}"

                # Dedup by (child_gk, parent_gk)
                pair = (source_gk, target_gk)
                if pair in seen:
                    continue
                seen.add(pair)

                edges.append(DependencyEdge(
                    source_gk=source_gk,
                    target_gk=target_gk,
                    edge_type="hard",
                    source_field=f"metadata.labels[{label_key}]",
                    detection_source="olm_deps:alm_label",
                    confidence=0.90,
                ))

        return edges

    def detect_alm_label_edges(
        self,
        service: str,
        registry: KindRegistry,
    ) -> list[DependencyEdge]:
        """Detect label-based parent-child edges from ALM examples.

        Fetches OLM CSV (using cache), extracts alm-examples,
        applies 5 precision gates, returns hard DependencyEdge list.
        """
        _, owned_gvks = self._extract_cached(service)

        csv = fetch_olm_csv(service)
        if csv is None:
            return []

        examples = extract_alm_examples(csv)
        if not examples:
            return []

        return self._extract_alm_label_edges(examples, owned_gvks, registry)
