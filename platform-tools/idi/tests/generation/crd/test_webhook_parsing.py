"""Tests for webhook configuration parsing (C21) in dep_adapters/rbac_deps.py."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.dep_adapters.rbac_deps import (
    _resolve_plural_resource,
    _strip_go_templates,
    extract_webhook_dependencies,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    """KindRegistry with core resources + some CRDs."""
    reg = KindRegistry()
    reg.register("Certificate", "certificates", "cert-manager.io")
    reg.register("Issuer", "issuers", "cert-manager.io")
    reg.register("ClusterIssuer", "clusterissuers", "cert-manager.io")
    return reg


def _write_template(chart_dir: Path, filename: str, content: str) -> None:
    """Write a template file into the chart's templates directory."""
    tpl_dir = chart_dir / "templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    (tpl_dir / filename).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# _strip_go_templates
# ---------------------------------------------------------------------------


class TestStripGoTemplates:
    def test_simple_replacement(self):
        result = _strip_go_templates("{{ .Values.foo }}")
        assert "{{" not in result
        assert "}}" not in result

    def test_cabundle_expression(self):
        result = _strip_go_templates("caBundle: {{ b64enc $cert.Cert }}")
        assert "caBundle:" in result
        assert "{{" not in result

    def test_no_templates(self):
        content = "key: value"
        assert _strip_go_templates(content) == content

    def test_trim_variants(self):
        result = _strip_go_templates("{{- .Values.x -}}")
        assert "{{" not in result
        assert "}}" not in result

    def test_result_is_yaml_parseable(self):
        import yaml
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: {{ include "chart.name" . }}
  annotations:
    cert-manager.io/inject-ca-from: {{ .Release.Namespace }}/{{ .Values.name }}
webhooks:
  - name: {{ .Values.webhookName }}
    clientConfig:
      caBundle: {{ b64enc $cert.Cert }}
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates"]
        operations: ["CREATE", "UPDATE"]
"""
        stripped = _strip_go_templates(content)
        # Should parse without error.
        docs = list(yaml.safe_load_all(stripped))
        assert len(docs) >= 1


# ---------------------------------------------------------------------------
# extract_webhook_dependencies
# ---------------------------------------------------------------------------


class TestExtractWebhookDependencies:
    def test_validating_webhook(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: my-webhook
webhooks:
  - name: validate.example.com
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates", "issuers"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert len(deps) >= 2
        sources = {d.source for d in deps}
        assert "rbac_deps:validating_webhook" in sources
        for d in deps:
            assert d.confidence == 0.85
            assert d.lineage_type == "reference"

    def test_mutating_webhook(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: my-mutating-webhook
webhooks:
  - name: mutate.example.com
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "mutating-webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert len(deps) >= 1
        assert all(d.source == "rbac_deps:mutating_webhook" for d in deps)

    def test_no_webhook_configs(self, tmp_path, registry):
        content = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
"""
        _write_template(tmp_path, "configmap.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert deps == []

    def test_templates_dir_missing(self, tmp_path, registry):
        # chart_path exists but templates/ does not.
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert deps == []

    def test_unknown_resources(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: my-webhook
webhooks:
  - name: validate.example.com
    rules:
      - apiGroups: ["example.com"]
        resources: ["widgets"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert deps == []

    def test_malformed_yaml(self, tmp_path, registry):
        content = "::: this is not valid yaml {{{[["
        _write_template(tmp_path, "broken.yaml", content)
        # Should not raise.
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert deps == []

    def test_wildcard_resources_skipped(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: my-webhook
webhooks:
  - name: validate.example.com
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["*"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert deps == []

    def test_wildcard_apigroups_skipped(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: my-webhook
webhooks:
  - name: validate.example.com
    rules:
      - apiGroups: ["*"]
        resources: ["certificates"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert deps == []

    def test_go_template_expressions_parsed(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: {{ include "chart.name" . }}-webhook
webhooks:
  - name: {{ .Values.webhookName }}
    clientConfig:
      caBundle: {{ b64enc $cert.Cert }}
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert len(deps) >= 1

    def test_api_group_cross_product(self, tmp_path, registry):
        """apiGroups x resources cross-product: all combinations resolved."""
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: my-webhook
webhooks:
  - name: validate.example.com
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates", "issuers"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        # certificates and issuers are both under cert-manager.io
        fields = {d.field for d in deps}
        assert "webhook:certificates" in fields
        assert "webhook:issuers" in fields

    def test_fact_ref_format(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: test
webhooks:
  - name: v.example.com
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        assert len(deps) >= 1
        dep = deps[0]
        assert dep.fact_ref.startswith("crdfacts://admissionregistration.k8s.io/")
        assert "#name" in dep.fact_ref

    def test_lineage_type(self, tmp_path, registry):
        content = """
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: test
webhooks:
  - name: v.example.com
    rules:
      - apiGroups: ["cert-manager.io"]
        resources: ["certificates"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
"""
        _write_template(tmp_path, "webhook.yaml", content)
        deps = extract_webhook_dependencies(str(tmp_path), registry)
        for d in deps:
            assert d.lineage_type == "reference"


# ---------------------------------------------------------------------------
# _resolve_plural_resource
# ---------------------------------------------------------------------------


class TestResolvePluralResource:
    def test_known_plural(self, registry):
        result = _resolve_plural_resource("certificates", "cert-manager.io", registry)
        assert result == "Certificate"

    def test_core_deployments(self, registry):
        result = _resolve_plural_resource("deployments", "apps", registry)
        assert result == "Deployment"

    def test_subresource_stripped(self, registry):
        result = _resolve_plural_resource("pods/status", "", registry)
        assert result == "Pod"

    def test_unknown_resource(self, registry):
        result = _resolve_plural_resource("widgets", "example.com", registry)
        assert result is None

    def test_naive_depluralisation(self, registry):
        """Naive depluralisation fallback: remove trailing s, capitalize."""
        result = _resolve_plural_resource("pods", "", registry)
        assert result == "Pod"
