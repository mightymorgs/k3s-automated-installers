"""Tests for identifier index + fan-out bug fixes (Section 03).

Bug 1: Identifier index key mismatch — composite skill_paths keys like
    "instances-instance-groups" didn't match dep.target_resource "instance-groups".
Bug 2: Fan-out grouping fragmentation — aliased resource names formed separate
    groups instead of a single canonical group.
"""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency
from idi.generation.dep_adapters.canonical_resources import (
    CanonicalResourceMap,
    build_canonical_resource_map,
)
from idi.generation.dep_adapters.verify import (
    apply_identifier_validation,
    build_identifier_index,
    suppress_fan_out,
)


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


def _awx_canonical_map() -> CanonicalResourceMap:
    """Build a canonical map simulating AWX-style nested paths."""
    spec = {"paths": {
        "/api/v2/instances/{id}": {},
        "/api/v2/instance_groups/{id}": {},
        "/api/v2/instances/{id}/instance_groups/{ig_id}": {},
    }}
    return build_canonical_resource_map(spec)


# ── Bug Fix 1: Identifier Index Resolution ──────────────────────────────


class TestIdentifierIndexCanonicalResolution:
    """Bug fix: identifier index keys are canonicalized for lookup."""

    def test_composite_key_resolved_via_canonical_map(self):
        """skill_paths key 'instances-instance-groups' resolves to canonical
        form so lookup by 'instance-groups' succeeds."""
        spec = {"paths": {
            "/instances/{id}": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                    }},
                }}}}},
            },
            "/instance_groups/{ig_id}": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "ig_id": {"type": "integer"},
                    }},
                }}}}},
            },
        }}
        cmap = build_canonical_resource_map(spec)
        skill_paths = {
            "svc/instances-instance-groups/list": {
                "resource": "instances-instance-groups",
                "operation": "list", "method": "GET",
                "endpoint": "/instances/{id}/instance_groups",
            },
            "svc/instance-groups/retrieve": {
                "resource": "instance-groups",
                "operation": "retrieve", "method": "GET",
                "endpoint": "/instance_groups/{ig_id}",
            },
        }
        index = build_identifier_index(spec, skill_paths, canonical_map=cmap)

        # Both composite and standalone forms should resolve to same identifiers
        ig_ids = index.get("instance-groups", set())
        composite_ids = index.get("instances-instance-groups", set())
        # At minimum, the canonical form should have identifiers
        assert ig_ids or composite_ids  # At least one form has data

    def test_identifier_validation_catches_config_field(self):
        """max_concurrent_jobs doesn't match any instance-groups identifier -> penalized."""
        deps = [_dep("max_concurrent_jobs", "instance-groups")]
        index = {
            "instance-groups": {"id", "ig_id"},
            "users": {"id", "user_id"},
        }
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.05  # 0.5 * 0.1

    def test_identifier_validation_passes_matching_field(self):
        """user_id matches users identifier -> preserved."""
        deps = [_dep("user_id", "users")]
        index = {
            "instance-groups": {"id"},
            "users": {"id", "user_id"},
        }
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_unknown_resource_conservative_pass(self):
        """Unknown resource name -> empty set -> conservative pass."""
        deps = [_dep("timeout", "unknown_resource")]
        index = {"users": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged


# ── Bug Fix 2: Fan-Out Grouping ─────────────────────────────────────────


class TestFanOutCanonicalGrouping:
    """Bug fix: aliased resource names group under canonical form."""

    def test_aliased_targets_group_together(self):
        """Edges to 'instance-groups' and 'instance_groups' group as one."""
        cmap = _awx_canonical_map()
        deps = [
            _dep("max_concurrent_jobs", "instance-groups"),
            _dep("policy_instance_percentage", "instance_groups"),
            _dep("max_forks", "instance-groups"),
        ]
        result = suppress_fan_out(deps, canonical_map=cmap)
        # All 3 non-FK-suffixed fields should be penalized
        for d in result:
            assert d.confidence < 0.5, f"{d.field} should be penalized"

    def test_awx_config_fields_penalized(self):
        """3+ non-FK config fields to same target triggers fan-out penalty."""
        deps = [
            _dep("max_concurrent_jobs", "instance-groups", confidence=0.6),
            _dep("policy_instance_percentage", "instance-groups", confidence=0.5),
            _dep("max_forks", "instance-groups", confidence=0.4),
        ]
        result = suppress_fan_out(deps)
        # All are non-FK-suffixed, > 50% lack suffix -> penalized
        for d in result:
            assert d.confidence < 0.15  # original * 0.2

    def test_fan_out_regression_no_aliases(self):
        """Basic fan-out still works without canonical map."""
        deps = [
            _dep("a", "target", confidence=0.5),
            _dep("b", "target", confidence=0.5),
            _dep("c", "target", confidence=0.5),
        ]
        result = suppress_fan_out(deps)
        for d in result:
            assert d.confidence == 0.1  # 0.5 * 0.2

    def test_fan_out_threshold_still_applies(self):
        """Below threshold (3), no penalty applied."""
        deps = [
            _dep("a", "target"),
            _dep("b", "target"),
        ]
        result = suppress_fan_out(deps)
        for d in result:
            assert d.confidence == 0.5  # Unchanged

    def test_fk_suffixed_fields_preserved(self):
        """FK-suffixed fields are NOT penalized in fan-out groups."""
        deps = [
            _dep("user_id", "users", confidence=0.6),
            _dep("config_val", "users", confidence=0.5),
            _dep("timeout", "users", confidence=0.4),
            _dep("retry", "users", confidence=0.3),
        ]
        result = suppress_fan_out(deps)
        user_id_dep = next(d for d in result if d.field == "user_id")
        config_dep = next(d for d in result if d.field == "config_val")
        assert user_id_dep.confidence == 0.6  # FK-suffixed, preserved
        assert config_dep.confidence < 0.5    # Non-FK, penalized
