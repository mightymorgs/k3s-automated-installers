"""CRD dep adapter — orchestrates schema walker + ref detector.

Thin orchestrator (~50 LOC) that wires walk_crd_schema/walk_crd_status
into classify_walked_field/detect_status_output and emits Dependencies
and Outputs using the dep adapter protocol.

Priority: 80 (above generic_odg at 50, below discriminator at 90).
"""
from __future__ import annotations

from typing import Any

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import classify_walked_field, detect_status_output
from idi.generation.crd.schema_walker import walk_crd_schema, walk_crd_status
from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output


class CrdDepAdapter:
    """Detects K8s CRD FK patterns via schema_walker + ref_detector pipeline."""

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

        # Extract spec schema from CRD body envelope.
        spec_schema = body.get("properties", {}).get("spec", {})
        if not spec_schema or "properties" not in spec_schema:
            spec_schema = body

        spec_properties = spec_schema.get("properties", {})
        spec_required = spec_schema.get("required", [])

        # Extract kind and group from body schema for detection context.
        kind = self._extract_kind(body)
        group = self._extract_group(body)

        results: list[Dependency] = []
        classified_ref_paths: set[str] = set()

        for field in walk_crd_schema(spec_properties, spec_required):
            # Parent-child deduplication: skip descendants of classified refs.
            if any(field.path.startswith(ref_path + ".") for ref_path in classified_ref_paths):
                continue

            # Get sibling fields for enum_kind detection.
            sibling_fields = None
            if field.schema.get("type") == "string" and field.schema.get("enum"):
                # Look up parent object properties for sibling detection.
                sibling_fields = self._get_sibling_fields(
                    spec_properties, field.parent_path, "spec",
                )

            classifications = classify_walked_field(
                field, self.registry, kind, group,
                sibling_fields=sibling_fields,
            )

            for classified in classifications:
                if classified.role != "input_ref" or not classified.target_kind:
                    continue

                classified_ref_paths.add(field.path)

                # Resolve target against known_resources.
                target_plural = self.registry.kind_to_plural(classified.target_kind)
                if not target_plural:
                    continue

                resolved, cross_service = self._resolve_target(
                    target_plural, known_resources,
                )
                if resolved is None:
                    continue

                dep_service = "k8s" if cross_service else operation.service
                target_group = classified.target_group or group
                target_field = classified.target_field or "name"

                satisfaction = (
                    "required_value" if classified.required
                    else "optional_with_default"
                )

                results.append(Dependency(
                    field=classified.field,
                    target_resource=resolved,
                    target_operation="create",
                    fact_ref=f"crdfacts://{target_group}/{classified.target_kind}#{target_field}",
                    confidence=classified.confidence,
                    source=f"crd_dep:{classified.detection_source}",
                    lineage_type="reference",
                    target_service=dep_service if cross_service else None,
                    satisfaction=satisfaction,
                ))

        return results

    def detect_outputs(
        self, operation: OperationInfo, spec: dict[str, Any],
    ) -> list[Output]:
        """Detect CRD status outputs using walk_crd_status + detect_status_output."""
        body = operation.body_schema
        if not body or "properties" not in body:
            return []

        # Extract status schema.
        status_schema = body.get("properties", {}).get("status", {})
        if not status_schema or "properties" not in status_schema:
            return []

        status_properties = status_schema["properties"]
        kind = self._extract_kind(body)
        group = self._extract_group(body)

        outputs: list[Output] = []
        for field in walk_crd_status(status_properties):
            result = detect_status_output(field, kind, group, self.registry)
            if result is None:
                continue
            # Only emit outputs above the 0.7 confidence threshold.
            if result.confidence < 0.7:
                continue

            target_group = result.target_group or group
            target_field = result.target_field or result.field.rsplit(".", 1)[-1]
            fact_ref = f"crdfacts://{target_group}/{result.target_kind}#{target_field}"

            outputs.append(Output(
                field=result.field,
                fact_ref=fact_ref,
                source=f"crd_dep:{result.detection_source}",
                priority=3 if operation.method == "POST" else 1,
            ))

        return outputs

    def _resolve_target(
        self, target: str, known_resources: set[str],
    ) -> tuple[str | None, bool]:
        """Resolve a K8s ref target against known resources.

        Handles both direct matches (secretstores in known) and
        lowercase normalization. Falls back to core K8s resources
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

    @staticmethod
    def _extract_kind(body: dict[str, Any]) -> str:
        """Extract Kind from body schema (from properties.kind.enum[0])."""
        kind_prop = body.get("properties", {}).get("kind", {})
        enum = kind_prop.get("enum", [])
        return enum[0] if enum else ""

    @staticmethod
    def _extract_group(body: dict[str, Any]) -> str:
        """Extract API group from body schema (from apiVersion enum)."""
        av_prop = body.get("properties", {}).get("apiVersion", {})
        enum = av_prop.get("enum", [])
        if enum:
            # apiVersion is like "cert-manager.io/v1" — group is before the /
            parts = enum[0].split("/")
            return parts[0] if len(parts) > 1 else ""
        return ""

    @staticmethod
    def _get_sibling_fields(
        root_properties: dict[str, Any],
        parent_path: str,
        prefix: str,
    ) -> dict[str, Any] | None:
        """Navigate to parent object's properties for sibling detection."""
        if parent_path == prefix:
            return root_properties

        # Walk the path segments to reach the parent.
        segments = parent_path[len(prefix) + 1:].split(".")
        current = root_properties
        for seg in segments:
            if not isinstance(current, dict):
                return None
            prop = current.get(seg, {})
            if not isinstance(prop, dict):
                return None
            # Handle arrays — dive into items.
            if prop.get("type") == "array":
                items = prop.get("items", {})
                if isinstance(items, dict) and "properties" in items:
                    current = items["properties"]
                else:
                    return None
            elif "properties" in prop:
                current = prop["properties"]
            else:
                return None
        return current
