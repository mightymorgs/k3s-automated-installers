"""Kubernetes CRD schema adapter.

Handles Kubernetes-specific FK detection patterns:
- SecretRef/ConfigMapRef/ServiceAccountRef patterns
- ObjectReference fields
- Cross-namespace references
- Namespaced vs cluster-scoped resources

Usage:
    adapter = KubernetesCrdAdapter(service="external-secrets", registry=registry)
    refs = adapter.extract_field_refs(schema, source_resource="externalsecret")
    outputs = adapter.extract_outputs(response_schema, resource="externalsecret", operation="create")
"""

import re
from typing import Dict, List, Any, Optional

from idi.generation.fact_model import ProducedFact, FactRef


# Fields to exclude from FK detection
EXCLUDED_FIELDS = frozenset({
    "status",           # Status is read-only
    "namespace",        # External input
    "apiVersion",       # Metadata
    "kind",             # Metadata
    "resourceVersion",  # Optimistic locking
    "selfLink",         # Deprecated
    "creationTimestamp",
    "deletionTimestamp",
    "deletionGracePeriodSeconds",
    "generation",
    "finalizers",
    "ownerReferences",  # Could be FK but complex
    "managedFields",
    "annotations",
    "labels",
    "selector",         # Label selectors, not direct refs
})

# ObjectReference and LabelSelector schema patterns to detect
OBJECT_REFERENCE_PATTERNS = [
    "io.k8s.api.core.v1.ObjectReference",
    "ObjectReference",
]

LABEL_SELECTOR_PATTERNS = [
    "io.k8s.apimachinery.pkg.apis.meta.v1.LabelSelector",
    "LabelSelector",
]

# Temporary compatibility shim — will be removed in section-05
# when crd_dep.py is updated to use the registry instead.
K8S_REF_PATTERNS: Dict[str, str] = {}


class KubernetesCrdAdapter:
    """Adapter for Kubernetes CRD schema FK detection and output extraction."""

    def __init__(self, service: str, registry=None, known_resources: Optional[set] = None):
        """Initialize adapter for a specific service.

        Args:
            service: Service name (e.g., 'external-secrets', 'cert-manager', 'k8s')
            registry: KindRegistry with core resources and CRDs registered
            known_resources: Optional set of known resource names for FK resolution
        """
        self.service = service
        self.registry = registry
        self.known_resources = known_resources or set()

    def extract_field_refs(
        self,
        schema: Optional[Dict[str, Any]],
        source_resource: str,
    ) -> List[Dict[str, Any]]:
        """Extract field references from a Kubernetes schema.

        Detects K8s-specific reference patterns like SecretRef, ConfigMapRef,
        ServiceAccountRef, and ObjectReference fields.

        Args:
            schema: OpenAPI schema dict
            source_resource: Name of the resource this schema belongs to

        Returns:
            List of dicts with {field, target_resource, type, source, cross_namespace}
        """
        if not schema or not isinstance(schema, dict):
            return []

        refs: List[Dict[str, Any]] = []
        properties = schema.get("properties", {})

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue

            # Skip excluded fields
            if prop_name in EXCLUDED_FIELDS or prop_name.lower() in EXCLUDED_FIELDS:
                continue

            # Check for $ref to ObjectReference or LabelSelector
            ref_value = prop_schema.get("$ref", "")
            if ref_value:
                # Skip LabelSelector - not a direct FK
                if any(pat in ref_value for pat in LABEL_SELECTOR_PATTERNS):
                    continue

                # ObjectReference is a generic FK
                if any(pat in ref_value for pat in OBJECT_REFERENCE_PATTERNS):
                    refs.append({
                        "field": prop_name,
                        "target_resource": "any",  # ObjectReference can point to anything
                        "type": "k8s_ref",
                        "source": "objectref",
                        "cross_namespace": True,  # ObjectReference always has namespace
                    })
                    continue

            # Check for known K8s ref patterns by field name
            target = self._match_ref_pattern(prop_name)
            if target:
                cross_namespace = self._has_namespace_property(prop_schema)
                refs.append({
                    "field": prop_name,
                    "target_resource": target,
                    "type": "k8s_ref",
                    "source": "k8s_ref_pattern",
                    "cross_namespace": cross_namespace,
                })
                continue

            # Check object with name property - might be a ref
            if prop_schema.get("type") == "object":
                inner_props = prop_schema.get("properties", {})
                if "name" in inner_props:
                    # Heuristic: field ending in Ref with name property is likely a ref
                    if prop_name.lower().endswith("ref"):
                        target = self._infer_target_from_field_name(prop_name)
                        cross_namespace = "namespace" in inner_props
                        refs.append({
                            "field": prop_name,
                            "target_resource": target,
                            "type": "k8s_ref",
                            "source": "k8s_ref_pattern",
                            "cross_namespace": cross_namespace,
                        })

            # Check for name fields that reference other resources
            if prop_name.lower().endswith("name") and prop_schema.get("type") == "string":
                target = self._match_ref_pattern(prop_name)
                if target:
                    refs.append({
                        "field": prop_name,
                        "target_resource": target,
                        "type": "k8s_ref",
                        "source": "k8s_name_pattern",
                        "cross_namespace": False,
                    })
                else:
                    # Check via registry for compound name patterns.
                    if self.registry:
                        is_ref, _, target_plural, _ = self.registry.is_ref_field(prop_name)
                        if is_ref and target_plural:
                            refs.append({
                                "field": prop_name,
                                "target_resource": target_plural,
                                "type": "k8s_ref",
                                "source": "k8s_name_pattern",
                                "cross_namespace": False,
                            })

        return refs

    def _match_ref_pattern(self, field_name: str) -> Optional[str]:
        """Match a field name to a known Kind reference.

        Returns target resource plural or None.
        """
        if self.registry:
            is_ref, _, target_plural, _ = self.registry.is_ref_field(field_name)
            if is_ref and target_plural:
                return target_plural
        return None

    def _has_namespace_property(self, schema: Dict[str, Any]) -> bool:
        """Check if schema has a namespace property (indicating cross-namespace ref).

        Args:
            schema: Property schema dict

        Returns:
            True if schema has namespace property
        """
        if schema.get("type") != "object":
            return False
        props = schema.get("properties", {})
        return "namespace" in props

    def _infer_target_from_field_name(self, field_name: str) -> str:
        """Infer target resource from a ref field name.

        Uses registry to resolve. Returns plural or falls back to naive pluralization.
        """
        if self.registry:
            is_ref, _, target_plural, _ = self.registry.is_ref_field(field_name)
            if is_ref and target_plural:
                return target_plural

        # Fallback: strip Ref, lowercase, best-effort pluralize.
        # Reached for CRD-specific refs not in registry.
        base = re.sub(r'[Rr]ef$', '', field_name)
        lower = base.lower()
        if lower.endswith('s'):
            return lower
        elif lower.endswith('y'):
            return lower[:-1] + 'ies'
        else:
            return lower + 's'

    def extract_outputs(
        self,
        response_schema: Optional[Dict[str, Any]],
        resource: str,
        operation: str,
    ) -> List[ProducedFact]:
        """Extract output facts from a K8s response schema.

        K8s resources typically output:
        - metadata.uid (unique identifier)
        - metadata.name (resource name)

        Args:
            response_schema: Response schema dict
            resource: Resource name
            operation: Operation name (create, retrieve, etc.)

        Returns:
            List of ProducedFact instances
        """
        outputs: List[ProducedFact] = []

        if not response_schema or not isinstance(response_schema, dict):
            return outputs

        properties = response_schema.get("properties", {})
        metadata = properties.get("metadata", {})

        if metadata.get("type") == "object":
            meta_props = metadata.get("properties", {})

            # Extract uid if present
            if "uid" in meta_props:
                outputs.append(ProducedFact(
                    ref=FactRef(
                        service=self.service,
                        resource=resource,
                        field="uid",
                    ),
                    skill_path=f"{self.service}/{resource}/{operation}.md",
                    response_field="metadata.uid",
                    operation=operation,
                ))

            # Extract name if present
            if "name" in meta_props:
                outputs.append(ProducedFact(
                    ref=FactRef(
                        service=self.service,
                        resource=resource,
                        field="name",
                    ),
                    skill_path=f"{self.service}/{resource}/{operation}.md",
                    response_field="metadata.name",
                    operation=operation,
                ))

        return outputs

    def is_namespaced(self, path: str) -> bool:
        """Determine if a resource is namespaced from its API path.

        Args:
            path: API path like '/apis/apps/v1/namespaces/{namespace}/deployments'

        Returns:
            True if resource is namespaced, False if cluster-scoped
        """
        # Namespaced resources have /namespaces/{namespace}/ in the path
        return "/namespaces/{namespace}" in path or "/namespaces/{namespace}/" in path
