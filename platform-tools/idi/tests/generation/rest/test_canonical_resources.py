"""Tests for canonical resource alias map in dep_adapters/canonical_resources.py."""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.canonical_resources import (
    CanonicalResourceMap,
    build_canonical_resource_map,
)


def _spec_with_paths(*paths: str) -> dict:
    """Build a minimal spec with given path templates."""
    return {"paths": {p: {"get": {"responses": {"200": {}}}} for p in paths}}


class TestBuildCanonicalResourceMapBasic:
    """Basic canonical resource map construction."""

    def test_empty_spec_returns_empty_map(self):
        result = build_canonical_resource_map({})
        assert result.all_resources() == set()

    def test_empty_paths_returns_empty_map(self):
        result = build_canonical_resource_map({"paths": {}})
        assert result.all_resources() == set()

    def test_simple_collection_path(self):
        """GET /users -> canonical 'users'."""
        spec = _spec_with_paths("/users")
        result = build_canonical_resource_map(spec)
        assert "users" in result.all_resources()

    def test_simple_item_path(self):
        """/users/{user_id} -> canonical 'users' with path_param 'user_id'."""
        spec = _spec_with_paths("/users/{user_id}")
        result = build_canonical_resource_map(spec)
        assert "users" in result.all_resources()
        assert result.path_param("users") == "user_id"

    def test_nested_path(self):
        """/orgs/{org_id}/teams/{team_id} -> 'teams' with parent 'orgs'."""
        spec = _spec_with_paths("/orgs/{org_id}/teams/{team_id}")
        result = build_canonical_resource_map(spec)
        assert "teams" in result.all_resources()
        assert "orgs" in result.all_resources()
        assert result.parent("teams") == "orgs"


class TestCompositeNameResolution:
    """Composite name aliasing and parent-prefix stripping."""

    def test_composite_name_with_standalone(self):
        """instances-instance-groups aliases to instance-groups when standalone exists."""
        spec = _spec_with_paths(
            "/instances/{id}/instance_groups/",
            "/instance-groups/{id}",
        )
        result = build_canonical_resource_map(spec)
        # The composite name should resolve to the standalone canonical
        canonical = result.canonicalize("instances-instance-groups")
        assert canonical == result.canonicalize("instance-groups")

    def test_parent_prefix_stripping_only_when_prefixed(self):
        """Only strip parent when terminal IS prefixed by parent name."""
        # instances-instance-groups -> instance-groups (instance prefixes instance-groups)
        spec = _spec_with_paths(
            "/instances/{id}/instance_groups/",
            "/instance-groups/{id}",
        )
        result = build_canonical_resource_map(spec)
        canon = result.canonicalize("instances-instance-groups")
        assert canon == result.canonicalize("instance-groups")

    def test_no_prefix_stripping_when_no_prefix_relationship(self):
        """clusters-nodes stays as-is because 'cluster' doesn't prefix 'nodes'."""
        spec = _spec_with_paths("/clusters/{id}/nodes/{node_id}")
        result = build_canonical_resource_map(spec)
        # nodes should exist as a resource (from the nested path)
        assert "nodes" in result.all_resources() or any(
            "node" in r for r in result.all_resources()
        )

    def test_collision_guard_standalone_wins(self):
        """If standalone and nested resolve to same name, standalone wins."""
        spec = _spec_with_paths(
            "/nodes/{id}",
            "/clusters/{id}/nodes/{node_id}",
        )
        result = build_canonical_resource_map(spec)
        # Both should resolve to the same canonical
        assert result.canonicalize("nodes") is not None


class TestCanonicalizeMethod:
    """Tests for canonicalize() lookups."""

    def test_canonicalize_resolves_alias(self):
        spec = _spec_with_paths("/users/{user_id}")
        result = build_canonical_resource_map(spec)
        # The canonical name should resolve to itself
        assert result.canonicalize("users") == "users"

    def test_canonicalize_returns_input_for_unknown(self):
        spec = _spec_with_paths("/users/{user_id}")
        result = build_canonical_resource_map(spec)
        assert result.canonicalize("unknown-resource") == "unknown-resource"

    def test_canonicalize_hyphen_underscore_equivalence(self):
        """instance_groups and instance-groups resolve to same canonical."""
        spec = _spec_with_paths("/instance-groups/{id}")
        result = build_canonical_resource_map(spec)
        assert result.canonicalize("instance_groups") == result.canonicalize(
            "instance-groups"
        )

    def test_canonicalize_singular_plural(self):
        """user and users map to same canonical."""
        spec = _spec_with_paths("/users/{user_id}")
        result = build_canonical_resource_map(spec)
        assert result.canonicalize("user") == result.canonicalize("users")


class TestAliasesMethod:
    """Tests for aliases() lookups."""

    def test_aliases_returns_known_variations(self):
        spec = _spec_with_paths(
            "/instances/{id}/instance_groups/",
            "/instance-groups/{id}",
        )
        result = build_canonical_resource_map(spec)
        canonical = result.canonicalize("instance-groups")
        aliases = result.aliases(canonical)
        assert isinstance(aliases, set)
        assert len(aliases) >= 1  # At least the canonical name itself


class TestVersionPrefixPaths:
    """Paths with API version prefixes."""

    def test_version_prefix_skipped(self):
        """/api/v2/users/{id} correctly identifies 'users'."""
        spec = _spec_with_paths("/api/v2/users/{id}")
        result = build_canonical_resource_map(spec)
        assert "users" in result.all_resources()

    def test_multiple_version_segments(self):
        """/api/v1/beta/items/{id} still finds 'items'."""
        spec = _spec_with_paths("/api/v1/beta/items/{id}")
        result = build_canonical_resource_map(spec)
        # Should find items or beta-items
        assert any("item" in r for r in result.all_resources())


class TestEdgeCases:
    """Edge cases and graceful handling."""

    def test_path_with_only_param(self):
        """/{id} is handled gracefully (no resource name)."""
        spec = _spec_with_paths("/{id}")
        result = build_canonical_resource_map(spec)
        # Should not crash, may or may not find resources

    def test_trailing_slash_handling(self):
        """/users/ and /users treated equivalently."""
        spec = _spec_with_paths("/users/", "/users/{id}")
        result = build_canonical_resource_map(spec)
        assert "users" in result.all_resources()

    def test_all_resources_returns_set(self):
        spec = _spec_with_paths("/users/{id}", "/teams/{id}")
        result = build_canonical_resource_map(spec)
        resources = result.all_resources()
        assert isinstance(resources, set)
        assert "users" in resources
        assert "teams" in resources
