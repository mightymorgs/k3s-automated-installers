"""Tests: Slimmed Cloudflare and GitHub adapters maintain parity.

Cloudflare: envelope unwrapping removed (replaced by section-06 envelope detector).
  Keep: path-based resource normalization (~70 LOC).

GitHub: external params, polymorphic body, nested output, integer FK, path param
  classification all removed (replaced by generic detectors from sections 01-07).
  Keep: alias resolution for node_id->id, login->name, full_name->name (~75 LOC).
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest


class TestCloudflareAdapterSlimmed:
    """Cloudflare adapter keeps only path-based resource normalization."""

    def test_loc_under_80(self):
        """Cloudflare adapter file is under 80 LOC after slimming."""
        from idi.generation.adapters import cloudflare
        source = Path(inspect.getfile(cloudflare))
        lines = source.read_text().splitlines()
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) <= 80, f"Cloudflare adapter has {len(non_empty)} non-empty lines"

    def test_envelope_methods_removed(self):
        """extract_response_schema and helper methods removed (not on class itself)."""
        from idi.generation.adapters.cloudflare import CloudflareAdapter
        own = CloudflareAdapter.__dict__
        assert "extract_response_schema" not in own
        assert "_find_result_in_schema" not in own
        assert "_flatten_schema" not in own
        assert "extract_path_parameters_as_outputs" not in own
        assert "is_cloudflare_wrapper_field" not in own

    def test_resource_normalization_preserved(self):
        """normalize_resource_name still works for deep Cloudflare paths."""
        from idi.generation.adapters.cloudflare import CloudflareAdapter
        adapter = CloudflareAdapter(service="cloudflare")
        assert adapter.normalize_resource_name("/accounts/{account_id}/access/apps/{app_id}") == "access-apps"
        assert adapter.normalize_resource_name("/zones/{zone_id}/dns_records/{dns_record_id}") == "zones-dns-records"
        assert adapter.normalize_resource_name("/accounts") == "accounts"

    def test_extends_openapi_rest(self):
        """CloudflareAdapter still extends OpenApiRestAdapter."""
        from idi.generation.adapters.cloudflare import CloudflareAdapter
        from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
        assert issubclass(CloudflareAdapter, OpenApiRestAdapter)


class TestGitHubAdapterSlimmed:
    """GitHub adapter keeps only alias resolution."""

    def test_loc_under_80(self):
        """GitHub adapter file is under 80 LOC after slimming."""
        from idi.generation.adapters import github_openapi
        source = Path(inspect.getfile(github_openapi))
        lines = source.read_text().splitlines()
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) <= 80, f"GitHub adapter has {len(non_empty)} non-empty lines"

    def test_bulk_methods_removed(self):
        """Vendor-specific methods removed from GitHub adapter (not overridden)."""
        from idi.generation.adapters.github_openapi import GitHubOpenApiAdapter
        own = GitHubOpenApiAdapter.__dict__
        # These should NOT be defined on the subclass (inherited from base is OK)
        assert "extract_field_refs" not in own
        assert "extract_outputs" not in own
        assert "extract_path_params_as_refs" not in own
        assert "_is_output_field" not in own
        assert "_extract_nested_outputs" not in own
        assert "_detect_fk" not in own
        assert "_extract_ref_name" not in own
        assert "_infer_resource" not in own

    def test_constants_removed(self):
        """EXTERNAL_PARAMS and OUTPUT_FIELDS removed."""
        import idi.generation.adapters.github_openapi as mod
        assert not hasattr(mod, "EXTERNAL_PARAMS")
        assert not hasattr(mod, "OUTPUT_FIELDS")

    def test_alias_resolution_preserved(self):
        """GitHubFactRef resolves node_id->id, login->name, full_name->name."""
        from idi.generation.adapters.github_openapi import GitHubFactRef
        ref_node = GitHubFactRef(service="github", resource="repos", field="node_id")
        assert ref_node.canonical_field == "id"

        ref_login = GitHubFactRef(service="github", resource="users", field="login")
        assert ref_login.canonical_field == "name"

        ref_full = GitHubFactRef(service="github", resource="repos", field="full_name")
        assert ref_full.canonical_field == "name"

    def test_github_aliases_preserved(self):
        """GITHUB_ALIASES dict still available."""
        from idi.generation.adapters.github_openapi import GITHUB_ALIASES
        assert GITHUB_ALIASES["node_id"] == "id"
        assert GITHUB_ALIASES["login"] == "name"
        assert GITHUB_ALIASES["full_name"] == "name"


class TestAdapterRegistryUpdated:
    """__init__.py registry updated correctly."""

    def test_swagger2_removed_from_registry(self):
        """'swagger' and 'swagger2' keys resolve to REST adapter, not Swagger2."""
        from idi.generation.adapters import get_adapter
        # Should get a REST adapter, not a Swagger2Adapter
        adapter = get_adapter(service="test", style="rest")
        from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
        assert isinstance(adapter, OpenApiRestAdapter)

    def test_swagger2_import_removed(self):
        """Swagger2Adapter no longer importable from adapters package."""
        import idi.generation.adapters as adapters_mod
        assert not hasattr(adapters_mod, "Swagger2Adapter")

    def test_remaining_adapters_accessible(self):
        """rest, cloudflare, vault, aws, github adapters still accessible."""
        from idi.generation.adapters import get_adapter
        # These should all succeed without error
        get_adapter(service="test", style="rest")
        get_adapter(service="cloudflare", style="cloudflare")
        get_adapter(service="vault", style="vault")
        get_adapter(service="test", style="aws")
        get_adapter(service="github", style="github")

    def test_detect_style_no_swagger(self):
        """detect_style never returns 'swagger' or 'swagger2'."""
        from idi.generation.adapters import AdapterRegistry
        registry = AdapterRegistry()
        swagger_spec = {"swagger": "2.0", "paths": {"/test": {}}}
        result = registry.detect_style("/test", service="test", spec=swagger_spec)
        assert result not in ("swagger", "swagger2")

    def test_swagger2_style_routes_to_rest(self):
        """Requesting style='swagger2' routes to REST adapter."""
        from idi.generation.adapters import get_adapter
        from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
        adapter = get_adapter(service="test", style="swagger2")
        assert isinstance(adapter, OpenApiRestAdapter)
