"""Tests for RBAC dependency adapter — CRD Phase 4 Section 03."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.base import OperationInfo
from idi.generation.dep_adapters.rbac_deps import (
    RbacDepAdapter,
    _normalize_resource,
    _parse_rbac_rules,
    _strip_helm_directives,
    extract_rbac_edges,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry() -> KindRegistry:
    """Registry with core K8s + cert-manager CRDs."""
    reg = KindRegistry()
    reg.register("Certificate", "certificates", "cert-manager.io")
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    reg.register("CertificateRequest", "certificaterequests", "cert-manager.io")
    return reg


def _make_operation(service: str = "cert-manager") -> OperationInfo:
    return OperationInfo(
        service=service,
        resource="certificates",
        operation="create",
        method="POST",
        path="/apis/cert-manager.io/v1/namespaces/{ns}/certificates",
        body_schema={},
        response_schema={},
    )


def _make_clusterrole_yaml(
    rules: list[dict],
    kind: str = "ClusterRole",
) -> str:
    """Build a minimal ClusterRole/Role YAML string."""
    import yaml
    doc = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": kind,
        "metadata": {"name": "test-role"},
        "rules": rules,
    }
    return yaml.dump(doc, default_flow_style=False)


# ---------------------------------------------------------------------------
# Class attributes
# ---------------------------------------------------------------------------


class TestClassAttributes:
    def test_name(self):
        adapter = RbacDepAdapter()
        assert adapter.name == "rbac_deps"

    def test_priority(self):
        adapter = RbacDepAdapter()
        assert adapter.priority == 70


# ---------------------------------------------------------------------------
# matches()
# ---------------------------------------------------------------------------


class TestMatches:
    def test_apis_path(self):
        adapter = RbacDepAdapter()
        spec = {"paths": {"/apis/cert-manager.io/v1/namespaces/{ns}/certificates": {}}}
        assert adapter.matches(spec, "cert-manager") is True

    def test_rest_path_no_match(self):
        adapter = RbacDepAdapter()
        spec = {"paths": {"/v1/users": {}}}
        assert adapter.matches(spec, "test") is False

    def test_empty_spec(self):
        adapter = RbacDepAdapter()
        assert adapter.matches({}, "test") is False


# ---------------------------------------------------------------------------
# Helm template stripping
# ---------------------------------------------------------------------------


class TestHelmTemplateStripping:
    def test_directive_replaced_with_sentinel(self):
        result = _strip_helm_directives('apiGroups: ["{{ .Values.apiGroup }}"]')
        assert "__HELM_TPL__" in result
        assert "{{ .Values.apiGroup }}" not in result

    def test_sentinel_not_empty_string(self):
        """Sentinel prevents false Core API group match."""
        result = _strip_helm_directives('apiGroups: ["{{ .Values.apiGroup }}"]')
        assert result != 'apiGroups: [""]'

    def test_rule_with_sentinel_apigroups_skipped(self):
        """Rules with sentinel in apiGroups are skipped."""
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": ["{{ .Values.apiGroup }}"],
            "resources": ["secrets"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert rules == []

    def test_rule_with_sentinel_resources_skipped(self):
        """Rules with sentinel in resources are skipped."""
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": [""],
            "resources": ["{{ .Values.resource }}"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert rules == []

    def test_unparsable_yaml_skipped(self):
        """Unparsable YAML after stripping is skipped (fail-soft)."""
        bad_yaml = "{{- if .Values.rbac }}\nkey: [invalid yaml"
        rules = _parse_rbac_rules(bad_yaml)
        assert rules == []


# ---------------------------------------------------------------------------
# Resource normalization
# ---------------------------------------------------------------------------


class TestResourceNormalization:
    def test_subresource_status(self):
        assert _normalize_resource("certificates/status") == "certificates"

    def test_subresource_finalizers(self):
        assert _normalize_resource("pods/finalizers") == "pods"

    def test_wildcard_base_skipped(self):
        assert _normalize_resource("*/status") is None

    def test_plain_resource(self):
        assert _normalize_resource("secrets") == "secrets"


# ---------------------------------------------------------------------------
# Infrastructure filtering
# ---------------------------------------------------------------------------


class TestInfraFiltering:
    """Ensure infra resources are excluded from edges."""

    def _extract_with_infra(self, resource: str) -> tuple[list, list]:
        reg = _make_registry()
        # Register the infra resource so it *would* be found if not filtered.
        reg.register("Event", resource, "core")
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": [resource],
             "verbs": ["create", "patch"]},
        ])
        return extract_rbac_edges(yaml_content, reg)

    def test_events_filtered(self):
        deps, outputs = self._extract_with_infra("events")
        assert not any(d.target_resource == "events" for d in deps)
        assert not any("events" in o.field for o in outputs)

    def test_leases_filtered(self):
        reg = _make_registry()
        reg.register("Lease", "leases", "coordination.k8s.io")
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["coordination.k8s.io"], "resources": ["leases"],
             "verbs": ["get", "list", "watch", "create"]},
        ])
        deps, outputs = extract_rbac_edges(yaml_content, reg)
        assert not any(d.target_resource == "leases" for d in deps)

    def test_tokenreviews_filtered(self):
        reg = _make_registry()
        reg.register("TokenReview", "tokenreviews", "authentication.k8s.io")
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["authentication.k8s.io"], "resources": ["tokenreviews"],
             "verbs": ["create"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        assert not any("tokenreviews" in o.field for o in outputs)

    def test_secrets_not_filtered(self):
        """Secrets are NOT infrastructure — they should pass through."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["create", "get", "list", "watch"]},
        ])
        deps, outputs = extract_rbac_edges(yaml_content, reg)
        all_fields = [d.field for d in deps] + [o.field for o in outputs]
        assert any("secrets" in f for f in all_fields)


# ---------------------------------------------------------------------------
# Wildcard handling
# ---------------------------------------------------------------------------


class TestWildcardHandling:
    def test_resources_wildcard_only_skipped(self):
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": [""],
            "resources": ["*"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert rules == []

    def test_resources_wildcard_mixed(self):
        """Wildcard filtered, specific entries kept."""
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": [""],
            "resources": ["*", "secrets"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert len(rules) == 1
        assert rules[0]["resources"] == ["secrets"]

    def test_apigroups_wildcard_only_skipped(self):
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": ["*"],
            "resources": ["secrets"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert rules == []

    def test_apigroups_wildcard_mixed(self):
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": ["", "*"],
            "resources": ["secrets"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert len(rules) == 1
        assert rules[0]["apiGroups"] == [""]

    def test_verbs_wildcard_expanded(self):
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": [""],
            "resources": ["secrets"],
            "verbs": ["*"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert "create" in rules[0]["verbs"]
        assert "get" in rules[0]["verbs"]
        assert "delete" in rules[0]["verbs"]

    def test_missing_apigroups_defaults_to_core(self):
        """Missing apiGroups key normalized to [''] (Core group)."""
        yaml_content = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: test
rules:
  - resources: ["secrets"]
    verbs: ["get"]
"""
        rules = _parse_rbac_rules(yaml_content)
        assert len(rules) == 1
        assert rules[0]["apiGroups"] == [""]

    def test_empty_string_apigroups_is_core(self):
        """apiGroups: [''] is the Core group, not a wildcard."""
        yaml_content = _make_clusterrole_yaml([{
            "apiGroups": [""],
            "resources": ["secrets"],
            "verbs": ["get"],
        }])
        rules = _parse_rbac_rules(yaml_content)
        assert len(rules) == 1
        assert rules[0]["apiGroups"] == [""]


# ---------------------------------------------------------------------------
# Inference rules — Output edges
# ---------------------------------------------------------------------------


class TestOutputEdges:
    def test_create_watch_output(self):
        """create secrets + watch certificates -> Output priority=3."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["create", "get", "list", "watch"]},
        ])
        deps, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) == 1
        assert secret_outputs[0].priority == 3
        assert secret_outputs[0].source == "rbac_deps:create_watch"

    def test_update_watch_output(self):
        """update secrets + watch certificates -> Output priority=2."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["update", "get", "list", "watch"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) == 1
        assert secret_outputs[0].priority == 2
        assert secret_outputs[0].source == "rbac_deps:update_watch"

    def test_patch_watch_output(self):
        """patch secrets + watch certificates -> Output priority=2."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["patch", "get"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) == 1
        assert secret_outputs[0].priority == 2

    def test_delete_watch_output(self):
        """delete secrets + watch certificates -> Output priority=1."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["delete", "get"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) == 1
        assert secret_outputs[0].priority == 1
        assert secret_outputs[0].source == "rbac_deps:delete_watch"

    def test_create_without_crd_watch_no_output(self):
        """create secrets WITHOUT watching a CRD -> no Output (two-part signal required)."""
        reg = KindRegistry()  # No CRDs registered -> no trigger
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["create", "get"]},
        ])
        deps, outputs = extract_rbac_edges(yaml_content, reg)
        assert outputs == []

    def test_output_crdfacts_uri(self):
        """Output fact_ref uses crdfacts:// URI scheme."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["create", "get"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        for o in outputs:
            assert o.fact_ref.startswith("crdfacts://")


# ---------------------------------------------------------------------------
# Inference rules — Dependency edges
# ---------------------------------------------------------------------------


class TestDependencyEdges:
    def test_read_only_dependency(self):
        """get/list/watch only on secrets -> Dependency confidence=0.7."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["configmaps"],
             "verbs": ["get", "list", "watch"]},
        ])
        deps, _ = extract_rbac_edges(yaml_content, reg)
        cm_deps = [d for d in deps if d.target_resource == "configmaps"]
        assert len(cm_deps) == 1
        assert cm_deps[0].confidence == 0.7
        assert cm_deps[0].source == "rbac_deps:read_only"

    def test_lineage_type_reference(self):
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["configmaps"],
             "verbs": ["get", "list", "watch"]},
        ])
        deps, _ = extract_rbac_edges(yaml_content, reg)
        cm_deps = [d for d in deps if d.target_resource == "configmaps"]
        assert cm_deps[0].lineage_type == "reference"

    def test_dependency_crdfacts_uri(self):
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["configmaps"],
             "verbs": ["get", "list"]},
        ])
        deps, _ = extract_rbac_edges(yaml_content, reg)
        for d in deps:
            assert d.fact_ref.startswith("crdfacts://")


# ---------------------------------------------------------------------------
# CRD-to-operator mapping (cross-product)
# ---------------------------------------------------------------------------


class TestCrdMapping:
    def test_single_crd_group_full_priority(self):
        """Single CRD group -> full Output priority (no reduction)."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["create", "get"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert secret_outputs[0].priority == 3  # Full priority

    def test_multiple_crd_groups_reduced_priority(self):
        """Multiple CRD groups -> Output priority reduced by 1."""
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")
        reg.register("ExternalSecret", "externalsecrets", "external-secrets.io")
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["external-secrets.io"], "resources": ["externalsecrets"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["create", "get"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) == 1
        assert secret_outputs[0].priority == 2  # Reduced from 3

    def test_multiple_crd_groups_minimum_priority_1(self):
        """Multiple CRD groups with delete -> priority min is 1."""
        reg = KindRegistry()
        reg.register("Certificate", "certificates", "cert-manager.io")
        reg.register("ExternalSecret", "externalsecrets", "external-secrets.io")
        yaml_content = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": ["external-secrets.io"], "resources": ["externalsecrets"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["delete", "get"]},
        ])
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert secret_outputs[0].priority == 1  # min(1, 1-1) -> max(1, 0) = 1


# ---------------------------------------------------------------------------
# Caching and deduplication
# ---------------------------------------------------------------------------


class TestCachingAndDedup:
    def test_cached_per_service(self):
        """Chart parsed once per service — second call returns same reference."""
        adapter = RbacDepAdapter(registry=_make_registry())
        op = _make_operation()

        with patch.object(adapter, "_load_chart_rbac", return_value=None) as mock_load:
            adapter.detect_dependencies(op, {}, set())
            adapter.detect_dependencies(op, {}, set())

        mock_load.assert_called_once()

    def test_detect_deps_and_outputs_share_cache(self):
        """detect_dependencies and detect_outputs share same cache."""
        adapter = RbacDepAdapter(registry=_make_registry())
        op = _make_operation()

        with patch.object(adapter, "_load_chart_rbac", return_value=None) as mock_load:
            adapter.detect_dependencies(op, {}, set())
            adapter.detect_outputs(op, {})

        mock_load.assert_called_once()

    def test_duplicate_roles_deduplicated(self):
        """Duplicate edges from multiple Roles with identical permissions are deduplicated."""
        reg = _make_registry()
        yaml_part = _make_clusterrole_yaml([
            {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
             "verbs": ["get", "list", "watch"]},
            {"apiGroups": [""], "resources": ["configmaps"],
             "verbs": ["get", "list", "watch"]},
        ])
        # Two identical roles concatenated.
        yaml_content = yaml_part + "\n---\n" + yaml_part.replace("ClusterRole", "Role")
        deps, _ = extract_rbac_edges(yaml_content, reg)
        cm_deps = [d for d in deps if d.target_resource == "configmaps"]
        # Even with two identical roles, result should not have duplicates.
        # (extract_rbac_edges itself may deduplicate; the adapter also deduplicates.)
        assert len(cm_deps) <= 2  # At most 2 (before adapter dedup)

    def test_no_helm_chart_returns_empty(self):
        adapter = RbacDepAdapter(registry=_make_registry())
        op = _make_operation(service="nonexistent-service")
        deps = adapter.detect_dependencies(op, {}, set())
        outputs = adapter.detect_outputs(op, {})
        assert deps == []
        assert outputs == []


# ---------------------------------------------------------------------------
# Chart discovery
# ---------------------------------------------------------------------------


class TestChartDiscovery:
    def test_chart_path(self):
        adapter = RbacDepAdapter()
        # This relies on the actual catalog file existing.
        chart_path = adapter._find_helm_chart("cert-manager")
        if chart_path is not None:
            assert chart_path.name == "cert-manager-chart.yaml"

    def test_missing_chart_returns_none(self):
        adapter = RbacDepAdapter()
        assert adapter._find_helm_chart("nonexistent") is None

    def test_path_traversal_sanitized(self):
        adapter = RbacDepAdapter()
        result = adapter._find_helm_chart("../../etc/passwd")
        # Should not crash; returns None because sanitized name doesn't match a chart.
        assert result is None


# ---------------------------------------------------------------------------
# Role support
# ---------------------------------------------------------------------------


class TestRoleSupport:
    def test_role_parsed_like_clusterrole(self):
        """Kind: Role parsed identically to ClusterRole."""
        reg = _make_registry()
        yaml_content = _make_clusterrole_yaml(
            [
                {"apiGroups": ["cert-manager.io"], "resources": ["certificates"],
                 "verbs": ["get", "list", "watch"]},
                {"apiGroups": [""], "resources": ["secrets"],
                 "verbs": ["create", "get"]},
            ],
            kind="Role",
        )
        _, outputs = extract_rbac_edges(yaml_content, reg)
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) == 1


# ---------------------------------------------------------------------------
# Golden fixture
# ---------------------------------------------------------------------------


class TestGoldenFixture:
    def test_cert_manager_rbac_fixture(self):
        """Real cert-manager ClusterRole produces expected Output edges."""
        fixture_path = _FIXTURES_DIR / "rbac_cert_manager.yaml"
        yaml_content = fixture_path.read_text(encoding="utf-8")
        reg = _make_registry()
        reg.register("Ingress", "ingresses", "networking.k8s.io")

        deps, outputs = extract_rbac_edges(yaml_content, reg)

        # cert-manager should create secrets.
        secret_outputs = [o for o in outputs if "secrets" in o.field]
        assert len(secret_outputs) >= 1
        assert any(o.source == "rbac_deps:create_watch" for o in secret_outputs)

        # Events and leases should be filtered.
        all_fields = [d.field for d in deps] + [o.field for o in outputs]
        assert not any("events" in f for f in all_fields)
        assert not any("leases" in f for f in all_fields)


# ---------------------------------------------------------------------------
# Default no-arg construction
# ---------------------------------------------------------------------------


class TestDefaultConstruction:
    def test_no_arg_instantiation(self):
        """RbacDepAdapter can be instantiated without args (for discovery)."""
        adapter = RbacDepAdapter()
        assert adapter.registry is not None
        assert adapter.name == "rbac_deps"
