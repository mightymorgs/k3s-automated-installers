"""CRD bridge dep adapter -- delegates to KubernetesCrdAdapter.

Bridges the schema-layer ``KubernetesCrdAdapter`` (which knows K8s FK
patterns like secretRef, configMapRef, issuerRef) into the dep adapter
protocol so these patterns are used during dependency detection.

Priority: 80 (above generic_odg at 50, below discriminator at 90).
"""
from __future__ import annotations

from typing import Any

from idi.generation.adapters.kubernetes_crd import (
    EXCLUDED_FIELDS,
    KubernetesCrdAdapter,
)
from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output


# Top-level K8s envelope fields to skip entirely.
_K8S_ENVELOPE = frozenset({"apiVersion", "kind", "metadata", "status"})


class CrdDepAdapter:
    """Detects K8s-specific FK patterns via KubernetesCrdAdapter bridge."""

    name = "crd_dep"
    priority = 80

    def __init__(self, registry: KindRegistry | None = None):
        """Initialize with an optional KindRegistry.

        The registry is optional to support the no-arg discovery pattern
        used by DepAdapterRegistry. When not provided, a default registry
        with only core resources is used.
        """
        self.registry = registry or KindRegistry()

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        """Match specs with K8s-style API paths."""
        for path in spec.get("paths", {}):
            if "/apis/" in path or path.startswith("/api/v1/namespaces"):
                return True
        return False

    def detect_dependencies(
        self,
        operation: OperationInfo,
        spec: dict[str, Any],
        known_resources: set[str],
    ) -> list[Dependency]:
        body = operation.body_schema
        if not body or "properties" not in body:
            return []

        adapter = KubernetesCrdAdapter(
            service=operation.service,
            registry=self.registry,
            known_resources=known_resources,
        )

        # CRD bodies are {apiVersion, kind, metadata, spec, status}.
        # Real FK fields live under spec.properties.
        spec_schema = body.get("properties", {}).get("spec", {})
        if not spec_schema or "properties" not in spec_schema:
            # Fallback: try the body itself (non-standard CRD).
            spec_schema = body

        results: list[Dependency] = []
        self._walk_and_detect(
            adapter, spec_schema, operation.service,
            known_resources, results, depth=0,
        )
        return results

    def _walk_and_detect(
        self,
        adapter: KubernetesCrdAdapter,
        schema: dict[str, Any],
        service: str,
        known_resources: set[str],
        results: list[Dependency],
        depth: int,
    ) -> None:
        """Walk schema tree, detect K8s refs at each level."""
        if depth > 6 or not isinstance(schema, dict):
            return

        refs = adapter.extract_field_refs(schema, "")
        for ref in refs:
            field = ref["field"]
            target = ref["target_resource"]
            if target == "any":
                continue  # ObjectReference -- too generic.

            # Resolve target against known_resources.
            resolved, cross_service = self._resolve_target(target, known_resources)
            if resolved is None:
                continue

            # Cross-service deps target the k8s service, not the source service.
            dep_service = "k8s" if cross_service else service
            confidence = 0.9 if ref.get("source") == "k8s_ref_pattern" else 0.7
            results.append(Dependency(
                field=field,
                target_resource=resolved,
                target_operation="create",
                fact_ref=f"facts://{dep_service}/{resolved}#id",
                confidence=confidence,
                source=f"crd_dep:{ref.get('source', 'unknown')}",
                lineage_type="reference",
                target_service=dep_service if cross_service else None,
            ))

        # Recurse into nested objects that extract_field_refs didn't handle.
        for prop_name, prop_schema in schema.get("properties", {}).items():
            if not isinstance(prop_schema, dict):
                continue
            if prop_name in _K8S_ENVELOPE or prop_name in EXCLUDED_FIELDS:
                continue
            # Skip fields we already matched (they are known refs).
            is_ref, _, _, _ = self.registry.is_ref_field(prop_name)
            if is_ref:
                continue

            # Recurse into nested objects.
            if prop_schema.get("type") == "object" and "properties" in prop_schema:
                self._walk_and_detect(
                    adapter, prop_schema, service,
                    known_resources, results, depth + 1,
                )

            # Recurse into array items.
            items = prop_schema.get("items", {})
            if (
                prop_schema.get("type") == "array"
                and isinstance(items, dict)
                and "properties" in items
            ):
                self._walk_and_detect(
                    adapter, items, service,
                    known_resources, results, depth + 1,
                )

    def _resolve_target(
        self, target: str, known_resources: set[str],
    ) -> tuple[str | None, bool]:
        """Resolve a K8s ref target against known resources.

        Handles both direct matches (secretstores in known) and
        lowercase normalization.  Falls back to core K8s resources
        for cross-service targets (e.g. cert-manager -> secrets).

        Returns:
            Tuple of (resolved_name, is_cross_service).
        """
        if target in known_resources:
            return target, False
        # Try lowercase match.
        lower_target = target.lower()
        for res in known_resources:
            if res.lower() == lower_target:
                return res, False
        # Allow core K8s resources (bootstrap set only) as cross-service targets.
        if lower_target in self.registry.core_plurals():
            return target, True
        return None, False

    def detect_outputs(
        self, operation: OperationInfo, spec: dict[str, Any],
    ) -> list[Output]:
        """Detect K8s-style outputs (metadata.uid, metadata.name)."""
        adapter = KubernetesCrdAdapter(
            service=operation.service,
            registry=self.registry,
        )
        facts = adapter.extract_outputs(
            operation.response_schema,
            operation.resource,
            operation.operation,
        )

        outputs: list[Output] = []
        for fact in facts:
            if hasattr(fact, "ref") and hasattr(fact.ref, "to_uri"):
                outputs.append(Output(
                    field=fact.response_field,
                    fact_ref=fact.ref.to_uri(),
                    source="crd_dep:k8s_output",
                    priority=3 if operation.method == "POST" else 1,
                ))
        return outputs
