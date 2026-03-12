"""Tests for adapters/__init__.py — Phase 2 Section 06 cleanup."""
from __future__ import annotations

import pytest

from idi.generation.adapters import AdapterRegistry, get_adapter


class TestAdapterRegistryCleanup:
    def test_no_kubernetes_key(self):
        """AdapterRegistry does not contain 'kubernetes' key."""
        reg = AdapterRegistry()
        assert "kubernetes" not in reg._adapters

    def test_no_k8s_key(self):
        """AdapterRegistry does not contain 'k8s' key."""
        reg = AdapterRegistry()
        assert "k8s" not in reg._adapters

    def test_no_crd_key(self):
        """AdapterRegistry does not contain 'crd' key."""
        reg = AdapterRegistry()
        assert "crd" not in reg._adapters

    def test_rest_adapter_works(self):
        """get_adapter(style='rest') still works."""
        adapter = get_adapter(service="test", style="rest")
        assert adapter is not None

    def test_cloudflare_adapter_works(self):
        """get_adapter(style='cloudflare') still works."""
        adapter = get_adapter(service="cloudflare", style="cloudflare")
        assert adapter is not None


class TestDetectStyle:
    def test_k8s_apis_path_returns_rest(self):
        """detect_style returns 'rest' for /apis/apps/v1 paths."""
        reg = AdapterRegistry()
        assert reg.detect_style("/apis/apps/v1/namespaces/default/deployments") == "rest"

    def test_k8s_api_v1_returns_rest(self):
        """detect_style returns 'rest' for /api/v1/ paths."""
        reg = AdapterRegistry()
        assert reg.detect_style("/api/v1/namespaces/default/configmaps") == "rest"

    def test_regular_rest_returns_rest(self):
        """detect_style returns 'rest' for regular REST paths."""
        reg = AdapterRegistry()
        assert reg.detect_style("/v1/users") == "rest"


class TestImportCleanup:
    def test_kubernetes_crd_adapter_not_in_all(self):
        """'KubernetesCrdAdapter' not in adapters.__all__."""
        import idi.generation.adapters as adapters_mod
        assert "KubernetesCrdAdapter" not in adapters_mod.__all__
