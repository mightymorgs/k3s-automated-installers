"""RBAC dependency adapter — extracts operator-resource edges from Helm chart RBAC rules.

Parses ClusterRole/Role resources from Helm chart templates to infer which
resources an operator creates, modifies, or reads.  Produces both Dependency
objects (read relationships) and Output objects (side-effect relationships).

Priority: 70 (above generic_odg at 50, below crd_dep at 80).
No import-time side effects.
"""
from __future__ import annotations

import io
import logging
import re
import tarfile
from pathlib import Path
from typing import Any

import yaml

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.base import Dependency, DetectionSource, OperationInfo, Output

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")
_HELM_TPL_RE = re.compile(r"\{\{.*?\}\}")
_HELM_TPL_SENTINEL = "__HELM_TPL__"

# Infrastructure resources: operational plumbing, not meaningful dep signals.
_INFRA_DENY_LIST: frozenset[str] = frozenset({
    "events",
    "leases",
    "subjectaccessreviews",
    "tokenreviews",
    "selfsubjectaccessreviews",
})

# All standard RBAC verbs (used when wildcard "*" appears in verbs).
_ALL_VERBS: frozenset[str] = frozenset({
    "create", "get", "list", "watch", "update", "patch", "delete",
})

_WRITE_VERBS = {"create", "update", "patch", "delete"}
_READ_VERBS = {"get", "list", "watch"}


def _strip_helm_directives(content: str) -> str:
    """Replace ``{{ ... }}`` with sentinel instead of empty string.

    Prevents false matches: ``apiGroups: ["{{ .Values.apiGroup }}"]``
    becomes ``apiGroups: ["__HELM_TPL__"]`` instead of ``apiGroups: [""]``
    which would falsely match the Core API group.
    """
    return _HELM_TPL_RE.sub(_HELM_TPL_SENTINEL, content)


def _normalize_verbs(verbs: list[str]) -> set[str]:
    """Expand wildcard verbs and return a normalized set."""
    if "*" in verbs:
        return set(_ALL_VERBS)
    return set(verbs)


def _filter_wildcards(items: list[str]) -> list[str]:
    """Remove wildcard entries from a list, keeping only specific values."""
    return [x for x in items if x != "*"]


def _normalize_resource(resource: str) -> str | None:
    """Normalize subresources and filter wildcard bases.

    ``certificates/status`` -> ``certificates``
    ``*/status`` -> None (skip)
    ``secrets`` -> ``secrets``
    """
    base = resource.split("/")[0]
    if base == "*":
        return None
    return base


def _parse_rbac_rules(yaml_content: str) -> list[dict[str, Any]]:
    """Parse all ClusterRole/Role rules from YAML content.

    Returns list of dicts with keys: apiGroups, resources, verbs.
    Fail-soft per document: unparsable YAML docs are skipped.
    """
    stripped = _strip_helm_directives(yaml_content)
    rules: list[dict[str, Any]] = []

    try:
        docs = list(yaml.safe_load_all(stripped))
    except yaml.YAMLError:
        logger.debug("Failed to parse YAML content for RBAC rules")
        return []

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        kind = doc.get("kind", "")
        if kind not in ("ClusterRole", "Role"):
            continue
        for rule in doc.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            api_groups = rule.get("apiGroups")
            if api_groups is None:
                api_groups = [""]  # K8s default: Core group
            resources = rule.get("resources") or []
            verbs = rule.get("verbs") or []

            # Filter wildcards from apiGroups and resources.
            api_groups = _filter_wildcards(api_groups)
            resources = _filter_wildcards(resources)

            if not api_groups or not resources:
                continue

            # Skip rules with sentinel values.
            if any(_HELM_TPL_SENTINEL in g for g in api_groups):
                continue
            if any(_HELM_TPL_SENTINEL in r for r in resources):
                continue

            rules.append({
                "apiGroups": api_groups,
                "resources": resources,
                "verbs": _normalize_verbs(verbs),
            })

    return rules


def _classify_resources(
    rules: list[dict[str, Any]],
    registry: KindRegistry,
) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """Classify resources into CRD triggers and non-CRD targets.

    Returns:
        (crd_groups, target_resources, target_verbs)
        - crd_groups: set of API groups that are CRD groups in KindRegistry
        - target_resources: plural -> set of apiGroups
        - target_verbs: plural -> set of verbs across all rules
    """
    crd_groups: set[str] = set()
    target_resources: dict[str, set[str]] = {}
    target_verbs: dict[str, set[str]] = {}

    for rule in rules:
        for group in rule["apiGroups"]:
            # Check if this group has registered CRD kinds.
            crd_kinds = registry.kinds_for_group(group)
            if crd_kinds and group != "" and group != "core":
                crd_groups.add(group)

        for resource in rule["resources"]:
            normalized = _normalize_resource(resource)
            if normalized is None:
                continue
            if normalized in _INFRA_DENY_LIST:
                continue
            # Check if resource is a known plural in registry.
            kind = registry.plural_to_kind(normalized)
            if kind is None:
                continue
            # Track verbs and groups per resource.
            target_verbs.setdefault(normalized, set()).update(rule["verbs"])
            target_resources.setdefault(normalized, set()).update(rule["apiGroups"])

    return crd_groups, target_resources, target_verbs


def extract_rbac_edges(
    yaml_content: str,
    registry: KindRegistry,
) -> tuple[list[Dependency], list[Output]]:
    """Parse Helm ClusterRole/Role templates for dependency signals.

    Returns ``(dependencies, outputs)`` separated to match DepAdapter protocol.
    """
    rules = _parse_rbac_rules(yaml_content)
    if not rules:
        return [], []

    crd_groups, target_resources, target_verbs = _classify_resources(rules, registry)

    # Determine if CRD groups watch their own resources (trigger signal).
    has_crd_watch = bool(crd_groups)
    n_crd_groups = len(crd_groups)

    deps: list[Dependency] = []
    outputs: list[Output] = []

    for resource_plural, verbs in target_verbs.items():
        groups = target_resources.get(resource_plural, set())
        kind = registry.plural_to_kind(resource_plural)
        if kind is None:
            continue

        group = registry.group_for_kind(kind) or ""

        # Skip CRD-group resources as targets (they are triggers, not targets).
        if any(g in crd_groups for g in groups):
            continue

        write_verbs = verbs & _WRITE_VERBS
        read_only = verbs <= _READ_VERBS and bool(verbs)

        if write_verbs and has_crd_watch:
            # Output edges: operator side-effects.
            if "create" in write_verbs:
                base_priority = 3
                source = "rbac_deps:create_watch"
            elif verbs & {"update", "patch"}:
                base_priority = 2
                source = "rbac_deps:update_watch"
            elif "delete" in write_verbs:
                base_priority = 1
                source = "rbac_deps:delete_watch"
            else:
                continue

            # Cross-product mitigation: lower priority when multiple CRD groups.
            priority = max(1, base_priority - 1) if n_crd_groups > 1 else base_priority

            outputs.append(Output(
                field=f"rbac:create:{resource_plural}" if "create" in write_verbs
                      else f"rbac:update:{resource_plural}" if verbs & {"update", "patch"}
                      else f"rbac:delete:{resource_plural}",
                fact_ref=f"crdfacts://{group}/{kind}#name",
                source=source,
                priority=priority,
            ))
        elif read_only:
            # Dependency edges: read-only access.
            deps.append(Dependency(
                field=f"rbac:read:{resource_plural}",
                target_resource=resource_plural,
                fact_ref=f"crdfacts://{group}/{kind}#name",
                confidence=0.7,
                source="rbac_deps:read_only",
                lineage_type="reference",
                detection_source=DetectionSource.DEFAULT,
            ))

    return deps, outputs


# ---------------------------------------------------------------------------
# Phase 5A (C21): Webhook configuration parsing
# ---------------------------------------------------------------------------

# Regex for stripping Go template expressions from Helm templates.
# Matches {{ ... }}, {{- ... }}, {{ ... -}}, and {{- ... -}} including
# multiline spans.  Uses non-greedy .*? to avoid over-matching.
_GO_TPL_RE = re.compile(r"\{\{-?\s*.*?\s*-?\}\}", re.DOTALL)


def _strip_go_templates(content: str) -> str:
    """Replace {{ ... }} Go template blocks with safe YAML placeholders.

    Handles: {{ .Values.x }}, {{ if ... }}...{{ end }}, {{ include ... }},
    {{ b64enc ... }}, and multiline template blocks.

    Uses 'placeholder' (no quotes) as replacement so adjacent templates
    on the same line merge into a single token rather than producing
    invalid YAML like '"placeholder"/"placeholder"'.
    """
    return _GO_TPL_RE.sub("placeholder", content)


def _resolve_plural_resource(
    plural: str,
    api_group: str,
    registry: KindRegistry,
) -> str | None:
    """Resolve a plural resource name to a Kind using KindRegistry.

    Uses KindRegistry's plural field for reverse lookup. Falls back to
    naive depluralisation (remove trailing 's') if not found.
    """
    # Strip subresource paths: pods/status -> pods.
    base = plural.split("/")[0] if "/" in plural else plural

    # Direct plural lookup.
    kind = registry.plural_to_kind(base)
    if kind is not None:
        return kind

    # Naive depluralisation: remove trailing 's', capitalize first letter.
    if base.endswith("s") and len(base) > 1:
        naive = base[:-1].capitalize()
        if naive in registry.all_kinds():
            return naive

    return None


def extract_webhook_dependencies(
    chart_path: str,
    registry: KindRegistry,
) -> list[Dependency]:
    """Parse Helm webhook configuration templates for dependency signals.

    Steps:
    1. Walk templates/ for YAML files
    2. Strip Go template expressions
    3. Parse with yaml.safe_load_all
    4. Extract webhook rules and resolve against KindRegistry
    5. Emit Dependency objects where target resource depends on webhook
    """
    templates_dir = Path(chart_path) / "templates"
    if not templates_dir.is_dir():
        return []

    results: list[Dependency] = []

    for yaml_file in sorted(templates_dir.iterdir()):
        if not yaml_file.is_file():
            continue
        if yaml_file.suffix not in (".yaml", ".yml"):
            continue

        try:
            raw_content = yaml_file.read_text(encoding="utf-8")
        except OSError:
            continue

        stripped = _strip_go_templates(raw_content)

        try:
            docs = list(yaml.safe_load_all(stripped))
        except yaml.YAMLError:
            logger.debug("Failed to parse webhook YAML: %s", yaml_file)
            continue

        for doc in docs:
            if not isinstance(doc, dict):
                continue
            doc_kind = doc.get("kind", "")
            if doc_kind not in (
                "ValidatingWebhookConfiguration",
                "MutatingWebhookConfiguration",
            ):
                continue

            is_validating = doc_kind == "ValidatingWebhookConfiguration"
            source = (
                "rbac_deps:validating_webhook"
                if is_validating
                else "rbac_deps:mutating_webhook"
            )

            webhooks = doc.get("webhooks") or []
            for webhook in webhooks:
                if not isinstance(webhook, dict):
                    continue
                rules = webhook.get("rules") or []
                for rule in rules:
                    if not isinstance(rule, dict):
                        continue
                    api_groups = rule.get("apiGroups") or []
                    resources = rule.get("resources") or []

                    # Wildcard handling: skip entirely.
                    if "*" in resources or "*" in api_groups:
                        continue

                    # Cross-product: apiGroups x resources.
                    for api_group in api_groups:
                        if not isinstance(api_group, str):
                            continue
                        for resource_plural in resources:
                            if not isinstance(resource_plural, str):
                                continue
                            resolved = _resolve_plural_resource(
                                resource_plural, api_group, registry,
                            )
                            if resolved is None:
                                continue

                            results.append(Dependency(
                                field=f"webhook:{resource_plural}",
                                target_resource=resource_plural,
                                target_operation="create",
                                fact_ref=(
                                    f"crdfacts://admissionregistration.k8s.io/"
                                    f"{doc_kind}#name"
                                ),
                                confidence=0.85,
                                source=source,
                                lineage_type="reference",
                                detection_source=DetectionSource.DEFAULT,
                            ))

    return results


def _extract_webhook_deps_from_content(
    yaml_content: str,
    registry: KindRegistry,
) -> list[Dependency]:
    """Extract webhook dependencies from in-memory YAML content.

    Used by RbacDepAdapter to parse webhook configs from already-loaded
    chart template content (same content used for RBAC extraction).
    """
    stripped = _strip_go_templates(yaml_content)
    results: list[Dependency] = []

    try:
        docs = list(yaml.safe_load_all(stripped))
    except yaml.YAMLError:
        return []

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        doc_kind = doc.get("kind", "")
        if doc_kind not in (
            "ValidatingWebhookConfiguration",
            "MutatingWebhookConfiguration",
        ):
            continue

        source = (
            "rbac_deps:validating_webhook"
            if doc_kind == "ValidatingWebhookConfiguration"
            else "rbac_deps:mutating_webhook"
        )

        for webhook in doc.get("webhooks") or []:
            if not isinstance(webhook, dict):
                continue
            for rule in webhook.get("rules") or []:
                if not isinstance(rule, dict):
                    continue
                api_groups = rule.get("apiGroups") or []
                resources = rule.get("resources") or []

                if "*" in resources or "*" in api_groups:
                    continue

                for api_group in api_groups:
                    if not isinstance(api_group, str):
                        continue
                    for resource_plural in resources:
                        if not isinstance(resource_plural, str):
                            continue
                        resolved = _resolve_plural_resource(
                            resource_plural, api_group, registry,
                        )
                        if resolved is None:
                            continue
                        results.append(Dependency(
                            field=f"webhook:{resource_plural}",
                            target_resource=resource_plural,
                            target_operation="create",
                            fact_ref=(
                                f"crdfacts://admissionregistration.k8s.io/"
                                f"{doc_kind}#name"
                            ),
                            confidence=0.85,
                            source=source,
                            lineage_type="reference",
                            detection_source=DetectionSource.DEFAULT,
                        ))

    return results


class RbacDepAdapter:
    """Detects K8s operator dependencies from Helm chart RBAC rules."""

    name = "rbac_deps"
    priority = 70

    def __init__(self, registry: KindRegistry | None = None) -> None:
        self.registry = registry or KindRegistry()
        self._cached: dict[str, tuple[list[Dependency], list[Output]]] = {}

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        """Match specs with K8s-style API paths."""
        for path in spec.get("paths", {}):
            if "/apis/" in path or path.startswith("/api/v1/namespaces"):
                return True
        return False

    def _find_helm_chart(self, service: str) -> Path | None:
        """Locate Helm chart metadata for a service."""
        safe_name = _SAFE_NAME_RE.sub("", service)
        chart_path = Path("catalog/specs/helm") / f"{safe_name}-chart.yaml"
        if chart_path.is_file():
            return chart_path
        return None

    def _load_chart_rbac(self, service: str) -> str | None:
        """Load RBAC YAML from a Helm chart archive.

        Returns concatenated YAML content of all ClusterRole/Role templates,
        or None if the chart is unavailable.
        """
        chart_path = self._find_helm_chart(service)
        if chart_path is None:
            return None

        try:
            chart_config = yaml.safe_load(chart_path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Failed to read chart metadata: %s", chart_path)
            return None

        if not isinstance(chart_config, dict):
            return None

        # Fetch chart archive from ArtifactHub.
        from idi.generation.crd.schema_loader import ARTIFACTHUB_API
        from urllib.request import Request, urlopen
        import json

        chart_name = chart_config.get("name", service)
        version = chart_config.get("version", "")
        # Build ArtifactHub API URL.
        # Use chart name as repo name (common convention).
        api_url = f"{ARTIFACTHUB_API}/packages/helm/{chart_name}/{chart_name}"
        if version:
            api_url += f"/{version}"

        try:
            req = Request(api_url, headers={"User-Agent": "IDI-CrdPipeline/1.0"})
            with urlopen(req, timeout=30) as resp:  # noqa: S310
                pkg_data = json.loads(resp.read())
        except Exception:
            logger.debug("Could not fetch ArtifactHub package for %s", service)
            return None

        content_url = pkg_data.get("content_url", "")
        if not content_url:
            return None

        try:
            req = Request(content_url, headers={"User-Agent": "IDI-CrdPipeline/1.0"})
            with urlopen(req, timeout=60) as resp:  # noqa: S310
                tgz_data = resp.read()
        except Exception:
            logger.debug("Could not download chart archive for %s", service)
            return None

        # Extract RBAC templates from the archive.
        rbac_yaml_parts: list[str] = []
        try:
            with tarfile.open(fileobj=io.BytesIO(tgz_data), mode="r:gz") as tar:
                for member in tar.getmembers():
                    # Validate path safety.
                    if member.name.startswith("/") or ".." in member.name:
                        continue
                    if not member.name.endswith(".yaml") and not member.name.endswith(".yml"):
                        continue
                    # Only look at templates directory.
                    if "/templates/" not in member.name:
                        continue
                    f = tar.extractfile(member)
                    if f:
                        rbac_yaml_parts.append(f.read().decode(errors="replace"))
        except Exception:
            logger.debug("Could not extract chart archive for %s", service)
            return None

        if not rbac_yaml_parts:
            return None

        return "\n---\n".join(rbac_yaml_parts)

    def _extract_cached(
        self, service: str,
    ) -> tuple[list[Dependency], list[Output]]:
        """Extract edges with per-service caching."""
        if service in self._cached:
            return self._cached[service]

        yaml_content = self._load_chart_rbac(service)
        if yaml_content is None:
            result: tuple[list[Dependency], list[Output]] = ([], [])
            self._cached[service] = result
            return result

        deps, outputs = extract_rbac_edges(yaml_content, self.registry)

        # Phase 5A (C21): Extract webhook dependencies from the same YAML content.
        webhook_deps = _extract_webhook_deps_from_content(yaml_content, self.registry)
        deps.extend(webhook_deps)

        # Intra-adapter deduplication.
        seen_deps: dict[tuple[str, str], Dependency] = {}
        for d in deps:
            key = (d.field, d.target_resource)
            if key not in seen_deps:
                seen_deps[key] = d
        seen_outputs: dict[str, Output] = {}
        for o in outputs:
            if o.fact_ref not in seen_outputs:
                seen_outputs[o.fact_ref] = o

        result = (list(seen_deps.values()), list(seen_outputs.values()))
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
        _, outputs = self._extract_cached(operation.service)
        return outputs
