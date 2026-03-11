"""Tests for path_deps: _match_segment normalization (s04) and nearest ancestor (s05)."""
from idi.generation.dep_adapters.base import OperationInfo
from idi.generation.dep_adapters.path_deps import _match_segment, detect_path_deps


class TestMatchSegmentNormalization:
    """Underscore-to-hyphen normalization in _match_segment."""

    def test_underscore_to_hyphen_exact_match(self):
        assert _match_segment("tag_protections", {"tag-protections"}) == "tag-protections"

    def test_underscore_to_hyphen_multi_word(self):
        assert _match_segment("user_groups", {"user-groups"}) == "user-groups"

    def test_no_underscore_unchanged(self):
        assert _match_segment("groups", {"groups"}) == "groups"

    def test_triple_segment_underscore(self):
        assert _match_segment("api_v3_series", {"api-v3-series"}) == "api-v3-series"

    def test_already_hyphenated_still_matches(self):
        """If segment already uses hyphens, normalization is a no-op."""
        assert _match_segment("tag-protections", {"tag-protections"}) == "tag-protections"

    def test_no_match_returns_none(self):
        assert _match_segment("nonexistent_resource", {"something-else"}) is None


def _op(path: str, service: str = "test-svc") -> OperationInfo:
    return OperationInfo(
        service=service, resource="test", operation="get_test",
        path=path, method="GET", body_schema={}, response_schema={},
    )


class TestNearestAncestor:
    """Section-05: Only emit nearest matching ancestor, not all ancestors."""

    def test_multi_level_only_nearest(self):
        """groupId should resolve to groups, NOT also to users."""
        deps = detect_path_deps(
            _op("/users/{id}/groups/{groupId}"),
            known_resources={"users", "groups"},
        )
        group_deps = [d for d in deps if d.field == "groupId"]
        assert len(group_deps) == 1
        assert group_deps[0].target_resource == "groups"

    def test_triple_level_only_nearest(self):
        """z should resolve to c only, not a or b."""
        deps = detect_path_deps(
            _op("/a/{x}/b/{y}/c/{z}"),
            known_resources={"a", "b", "c"},
        )
        z_deps = [d for d in deps if d.field == "z"]
        assert len(z_deps) == 1
        assert z_deps[0].target_resource == "c"

    def test_single_level_unchanged(self):
        """Single-level path still resolves to its parent."""
        deps = detect_path_deps(
            _op("/users/{id}"),
            known_resources={"users"},
        )
        assert len(deps) == 1
        assert deps[0].target_resource == "users"

    def test_no_ancestor_falls_back_to_param_name(self):
        """When no ancestor segment matches, fall back to param-name inference."""
        deps = detect_path_deps(
            _op("/api/v1/{realmId}"),
            known_resources={"realms"},
        )
        assert len(deps) == 1
        assert deps[0].target_resource == "realms"
        assert deps[0].confidence == 0.6  # fallback confidence

    def test_nearest_ancestor_confidence_0_8(self):
        """Nearest ancestor always gets confidence 0.8."""
        deps = detect_path_deps(
            _op("/users/{id}/groups/{groupId}"),
            known_resources={"users", "groups"},
        )
        group_deps = [d for d in deps if d.field == "groupId"]
        assert group_deps[0].confidence == 0.8

    def test_structural_match_over_param_name(self):
        """{groupId} under /entries/ resolves to 'entries' (structural), not 'groups'."""
        deps = detect_path_deps(
            _op("/items/{id}/entries/{groupId}"),
            known_resources={"items", "entries", "groups"},
        )
        group_deps = [d for d in deps if d.field == "groupId"]
        assert len(group_deps) == 1
        # Nearest ancestor "entries" wins — no param-name cross-check override
        assert group_deps[0].target_resource == "entries"

    def test_consistent_param_no_override(self):
        """{userId} under /users/ keeps 'users' — prefix is consistent."""
        deps = detect_path_deps(
            _op("/users/{userId}"),
            known_resources={"users"},
        )
        assert len(deps) == 1
        assert deps[0].target_resource == "users"

    def test_existing_multi_level_gets_single_edge(self):
        """Multi-level path emits one edge per param, not one per ancestor."""
        deps = detect_path_deps(
            _op("/orgs/{orgId}/repos/{repoId}/issues/{issueId}"),
            known_resources={"orgs", "repos", "issues"},
        )
        # Each param should produce exactly one dep
        for param in ("orgId", "repoId", "issueId"):
            param_deps = [d for d in deps if d.field == param]
            assert len(param_deps) == 1, f"{param} should have exactly 1 dep"
