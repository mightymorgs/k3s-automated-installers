"""Tests for Phase C adapter slimming — vault.py, aws_query.py, __init__.py.

Verifies output parity after removing redundant vendor-specific code that is
now handled by generic detection algorithms (envelope detection, response tree
walk, nested FK detection, credential exclusion, FK suffix expansion).
"""
from __future__ import annotations

import inspect
import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CATALOG_SPECS = Path(__file__).resolve().parents[5] / "catalog" / "specs"


def _run_pipeline_on_spec(spec_path: str, service_name: str, style: str = "auto"):
    """Run the full REST pipeline on a spec file and return stats + edges."""
    from idi.generation.cli import generate
    from idi.generation.spec_loader import create_context

    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = create_context(
            schema_path=spec_path,
            output_dir=tmpdir,
            api_name=service_name,
            style=style,
        )
        stats = generate(ctx)

        edges = []
        for json_file in Path(tmpdir).rglob("*.json"):
            try:
                data = json.loads(json_file.read_text())
                field_refs = data.get("field_refs", {})
                for field, fact_ref in field_refs.items():
                    edges.append({"field": field, "fact_ref": fact_ref})
            except (json.JSONDecodeError, KeyError):
                continue

        return {"stats": stats, "edges": edges}


# ---------------------------------------------------------------------------
# Vault adapter slimming tests
# ---------------------------------------------------------------------------

class TestVaultSlimmedAdapter:
    """Verify Vault adapter retains only vendor-unique behavior."""

    def test_vault_adapter_loc_under_120(self):
        """Count non-blank, non-comment lines in vault.py. Must be < 120."""
        from idi.generation.adapters import vault
        source = Path(inspect.getfile(vault))
        lines = source.read_text().splitlines()
        loc = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
        assert loc <= 120, f"vault.py has {loc} non-blank non-comment lines (max 120)"

    def test_backend_detection_preserved(self):
        """detect_backend_type() still correctly identifies backend types."""
        from idi.generation.adapters.vault import VaultAdapter
        adapter = VaultAdapter(service="vault")
        assert adapter.detect_backend_type("/auth/ldap/config") == "auth"
        assert adapter.detect_backend_type("/secret/data/mykey") == "kv_v2"
        assert adapter.detect_backend_type("/secret/mykey") == "kv_v1"
        assert adapter.detect_backend_type("/sys/policy") == "sys"
        assert adapter.detect_backend_type("/database/config/mydb") == "database"
        assert adapter.detect_backend_type("/pki/issue/myrole") == "pki"
        assert adapter.detect_backend_type("/ssh/sign/myrole") == "ssh"
        assert adapter.detect_backend_type("/transit/encrypt/mykey") == "transit"
        assert adapter.detect_backend_type("/unknown/path") == "unknown"

    def test_mount_parameterization_preserved(self):
        """parameterize_mount_point() converts concrete auth paths."""
        from idi.generation.adapters.vault import VaultAdapter
        adapter = VaultAdapter(service="vault")
        path, mount = adapter.parameterize_mount_point("/auth/ldap/config")
        assert path == "/auth/{mount}/config"
        assert mount == "ldap"

        path, mount = adapter.parameterize_mount_point("/auth/oidc/role/reader")
        assert path == "/auth/{mount}/role/reader"
        assert mount == "oidc"

        # Non-auth path unchanged
        path, mount = adapter.parameterize_mount_point("/secret/data/mykey")
        assert path == "/secret/data/mykey"
        assert mount is None

    def test_mount_dependency_extraction_preserved(self):
        """extract_mount_dependencies() emits sys-auth dependency for auth paths."""
        from idi.generation.adapters.vault import VaultAdapter
        adapter = VaultAdapter(service="vault")
        deps = adapter.extract_mount_dependencies("/auth/ldap/config", {})
        assert len(deps) == 1
        assert deps[0]["path"] == "vault/sys-auth/create"

        # Non-auth path has no mount deps
        deps = adapter.extract_mount_dependencies("/secret/mykey", {})
        assert len(deps) == 0

    def test_extract_response_schema_removed(self):
        """VaultAdapter should no longer have extract_response_schema()."""
        from idi.generation.adapters.vault import VaultAdapter
        assert "extract_response_schema" not in VaultAdapter.__dict__

    def test_extract_field_refs_removed(self):
        """VaultAdapter should no longer have extract_field_refs()."""
        from idi.generation.adapters.vault import VaultAdapter
        assert "extract_field_refs" not in VaultAdapter.__dict__

    def test_extract_outputs_removed(self):
        """VaultAdapter should no longer have extract_outputs()."""
        from idi.generation.adapters.vault import VaultAdapter
        assert "extract_outputs" not in VaultAdapter.__dict__

    def test_kv_auth_helpers_removed(self):
        """Backend-specific helper methods removed."""
        from idi.generation.adapters.vault import VaultAdapter
        assert "handle_kv_backend" not in VaultAdapter.__dict__
        assert "handle_auth_backend" not in VaultAdapter.__dict__

    def test_backend_response_paths_removed(self):
        """BACKEND_RESPONSE_PATHS dict removed from module."""
        import idi.generation.adapters.vault as vault_mod
        assert not hasattr(vault_mod, "BACKEND_RESPONSE_PATHS")

    def test_auth_output_facts_removed(self):
        """AUTH_OUTPUT_FACTS dict removed from module."""
        import idi.generation.adapters.vault as vault_mod
        assert not hasattr(vault_mod, "AUTH_OUTPUT_FACTS")

    def test_excluded_fields_removed(self):
        """EXCLUDED_FIELDS set removed from module."""
        import idi.generation.adapters.vault as vault_mod
        assert not hasattr(vault_mod, "EXCLUDED_FIELDS")

    def test_known_auth_types_preserved(self):
        """KNOWN_AUTH_TYPES list still available."""
        from idi.generation.adapters.vault import KNOWN_AUTH_TYPES
        assert isinstance(KNOWN_AUTH_TYPES, list)
        assert "ldap" in KNOWN_AUTH_TYPES
        assert "oidc" in KNOWN_AUTH_TYPES
        assert len(KNOWN_AUTH_TYPES) >= 14


# ---------------------------------------------------------------------------
# AWS adapter slimming tests
# ---------------------------------------------------------------------------

class TestAwsSlimmedAdapter:
    """Verify AWS adapter retains only vendor-unique behavior."""

    def test_aws_adapter_loc_under_160(self):
        """Count non-blank, non-comment lines in aws_query.py. Must be < 160."""
        from idi.generation.adapters import aws_query
        source = Path(inspect.getfile(aws_query))
        lines = source.read_text().splitlines()
        loc = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
        assert loc <= 160, f"aws_query.py has {loc} non-blank non-comment lines (max 160)"

    def test_arn_pattern_recognition_preserved(self):
        """ARN pattern recognition still works."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        adapter = AwsQueryAdapter(service="ec2")
        result = adapter._detect_arn_service("^arn:aws:iam::")
        assert result == "iam"
        result = adapter._detect_arn_service("^arn:aws:ec2:")
        assert result == "ec2"
        result = adapter._detect_arn_service("")
        assert result is None

    def test_id_prefix_matching_preserved(self):
        """AWS ID prefix patterns still work."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        adapter = AwsQueryAdapter(service="ec2")
        assert adapter._detect_id_pattern("^i-[a-f0-9]+$") == "instances"
        assert adapter._detect_id_pattern("^vpc-[a-f0-9]+$") == "vpcs"
        assert adapter._detect_id_pattern("") is None

    def test_action_crud_mapping_preserved(self):
        """action_to_operation() maps AWS actions to CRUD operations."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        adapter = AwsQueryAdapter(service="ec2")
        assert adapter.action_to_operation("CreateInstance") == "create"
        assert adapter.action_to_operation("DescribeVpcs") == "list"
        assert adapter.action_to_operation("DeleteSecurityGroup") == "delete"
        assert adapter.action_to_operation("ModifyInstanceAttribute") == "update"

    def test_field_suffix_map_preserved(self):
        """FIELD_SUFFIX_MAP with AWS PascalCase entries still works."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        adapter = AwsQueryAdapter(service="ec2")
        assert adapter._detect_field_suffix("InstanceId") == "instances"
        assert adapter._detect_field_suffix("VpcId") == "vpcs"
        assert adapter._detect_field_suffix("SubnetId") == "subnets"

    def test_extract_outputs_removed(self):
        """AwsQueryAdapter should no longer have extract_outputs()."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        assert "extract_outputs" not in AwsQueryAdapter.__dict__

    def test_action_to_resource_preserved(self):
        """action_to_resource() converts actions to resource names."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        adapter = AwsQueryAdapter(service="ec2")
        assert adapter.action_to_resource("RunInstances") == "instances"
        assert adapter.action_to_resource("CreateSecurityGroup") == "security-groups"

    def test_extract_field_refs_preserved(self):
        """extract_field_refs() still detects AWS-specific FK patterns."""
        from idi.generation.adapters.aws_query import AwsQueryAdapter
        adapter = AwsQueryAdapter(service="ec2")
        schema = {
            "properties": {
                "InstanceId": {"type": "string"},
                "VpcId": {"type": "string"},
            }
        }
        refs = adapter.extract_field_refs(schema, "security-groups")
        assert len(refs) == 2
        targets = {r["target_resource"] for r in refs}
        assert "instances" in targets
        assert "vpcs" in targets


# ---------------------------------------------------------------------------
# __init__.py registry slimming tests
# ---------------------------------------------------------------------------

class TestAdapterRegistrySlimmed:
    """Verify adapter registry works with simplified dispatch."""

    def test_init_loc_under_100(self):
        """Count non-blank, non-comment lines in __init__.py. Must be <= 100."""
        from idi.generation import adapters
        source = Path(inspect.getfile(adapters))
        lines = source.read_text().splitlines()
        loc = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
        assert loc <= 100, f"__init__.py has {loc} non-blank non-comment lines (max 100)"

    def test_registry_routes_to_remaining_adapters(self):
        """get_adapter() routes to correct adapter classes."""
        from idi.generation.adapters import get_adapter
        from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
        from idi.generation.adapters.cloudflare import CloudflareAdapter
        from idi.generation.adapters.vault import VaultAdapter
        from idi.generation.adapters.aws_query import AwsQueryAdapter

        assert isinstance(get_adapter(service="test", style="rest"), OpenApiRestAdapter)
        assert isinstance(get_adapter(service="cloudflare", style="cloudflare"), CloudflareAdapter)
        assert isinstance(get_adapter(service="vault", style="vault"), VaultAdapter)
        assert isinstance(get_adapter(service="test", style="aws"), AwsQueryAdapter)

    def test_auto_detect_vault(self):
        """detect_style() returns 'vault' for Vault specs."""
        from idi.generation.adapters import AdapterRegistry
        registry = AdapterRegistry()
        assert registry.detect_style("", service="vault") == "vault"
        assert registry.detect_style("", service="hashicorp-vault") == "vault"

    def test_auto_detect_cloudflare(self):
        """detect_style() returns 'cloudflare' for Cloudflare service."""
        from idi.generation.adapters import AdapterRegistry
        registry = AdapterRegistry()
        assert registry.detect_style("", service="cloudflare") == "cloudflare"

    def test_auto_detect_aws(self):
        """detect_style() returns 'aws' for AWS Query paths."""
        from idi.generation.adapters import AdapterRegistry
        registry = AdapterRegistry()
        assert registry.detect_style("?Action=DescribeVpcs", service="ec2") == "aws"

    def test_auto_detect_default_rest(self):
        """detect_style() returns 'rest' for unknown services."""
        from idi.generation.adapters import AdapterRegistry
        registry = AdapterRegistry()
        assert registry.detect_style("/api/v1/users", service="test") == "rest"

    def test_cloudflare_spec_detection_removed(self):
        """_is_cloudflare_spec and _has_cloudflare_wrapper removed from module."""
        import idi.generation.adapters as adapters_mod
        assert not hasattr(adapters_mod, "_is_cloudflare_spec")
        assert not hasattr(adapters_mod, "_has_cloudflare_wrapper")

    def test_github_adapter_still_accessible(self):
        """GitHub adapter still accessible via 'github' style."""
        from idi.generation.adapters import get_adapter
        adapter = get_adapter(service="github", style="github")
        assert adapter is not None


# ---------------------------------------------------------------------------
# Overall LOC verification
# ---------------------------------------------------------------------------

class TestOverallLOCTarget:
    """Verify total vendor-specific LOC meets the target."""

    def test_total_vendor_loc_under_793(self):
        """Sum non-blank, non-comment lines across all adapter files.

        Files: cloudflare.py, github_openapi.py, vault.py, aws_query.py, __init__.py.
        swagger2.py should not exist (deleted in section 08).
        openapi_rest.py is the generic base and does not count toward vendor LOC.
        """
        from idi.generation import adapters
        from idi.generation.adapters import cloudflare, github_openapi, vault, aws_query

        total = 0
        for mod in [cloudflare, github_openapi, vault, aws_query, adapters]:
            source = Path(inspect.getfile(mod))
            lines = source.read_text().splitlines()
            loc = sum(1 for l in lines if l.strip() and not l.strip().startswith("#"))
            total += loc

        assert total <= 793, f"Total vendor LOC is {total} (max 793)"

    def test_swagger2_does_not_exist(self):
        """swagger2.py was deleted in section 08."""
        from idi.generation import adapters
        adapters_dir = Path(inspect.getfile(adapters)).parent
        assert not (adapters_dir / "swagger2.py").exists()


# ---------------------------------------------------------------------------
# Pipeline parity tests — verify slimmed adapters don't regress edge counts
# ---------------------------------------------------------------------------

class TestPipelineParity:
    """Verify slimmed adapters produce equal or better pipeline results.

    Runs the full pipeline on real specs and checks edge counts against
    baselines captured from section-04 (post-Phase A). The slimmed adapters
    must not reduce edge detection — generic detectors now cover what was
    removed from the vendor adapters.
    """

    # Baselines from test_phase_a_integration.py TestEdgeCountRegression
    VAULT_BASELINE = 10

    def test_vault_pipeline_parity(self, vault_spec):
        """Vault pipeline edge count must equal or exceed Phase A baseline.

        Slimmed vault.py removed extract_response_schema, extract_field_refs,
        and extract_outputs. Generic detectors (envelope, FK suffix, response
        tree walk) must cover this.
        """
        spec_path = str(CATALOG_SPECS / "vault-openapi.json")
        result = _run_pipeline_on_spec(spec_path, "vault", style="vault")
        assert result["stats"]["resources"] >= 1
        assert result["stats"]["skills"] >= 1
        assert len(result["edges"]) >= self.VAULT_BASELINE, (
            f"Vault edge count regressed after slimming: "
            f"{len(result['edges'])} < {self.VAULT_BASELINE}"
        )

    def test_vault_pipeline_no_errors(self, vault_spec):
        """Vault pipeline completes without exceptions after slimming."""
        spec_path = str(CATALOG_SPECS / "vault-openapi.json")
        result = _run_pipeline_on_spec(spec_path, "vault", style="vault")
        assert result["stats"]["resources"] >= 1

    def test_authentik_pipeline_unaffected(self, authentik_spec):
        """Authentik pipeline (REST, no vendor adapter) unaffected by slimming."""
        spec_path = str(CATALOG_SPECS / "authentik-openapi.json")
        result = _run_pipeline_on_spec(spec_path, "authentik")
        assert result["stats"]["resources"] >= 1
        assert len(result["edges"]) >= 10

    def test_sonarr_pipeline_unaffected(self, sonarr_spec):
        """Sonarr pipeline (REST, no vendor adapter) unaffected by slimming."""
        spec_path = str(CATALOG_SPECS / "sonarr-openapi.json")
        result = _run_pipeline_on_spec(spec_path, "sonarr")
        assert result["stats"]["resources"] >= 1
        assert len(result["edges"]) >= 5
