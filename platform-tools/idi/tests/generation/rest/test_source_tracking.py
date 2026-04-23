"""Tests for source-of-match origin tracking in _build_candidates()."""
from __future__ import annotations

from idi.generation.dep_adapters.target_inference import _build_candidates, infer_target


class TestBuildCandidatesOrigin:
    """Verify _build_candidates returns 3-tuples with correct origin tags."""

    def test_no_container_all_field_origin(self):
        """Without a container, all candidates should be 'field' origin."""
        candidates = _build_candidates("series_id", None)
        assert all(len(c) == 3 for c in candidates), "Expected 3-tuples"
        assert all(c[2] == "field" for c in candidates), "All should be 'field' origin"

    def test_container_candidates_have_container_origin(self):
        """Container suffix subsequences should have 'container' origin."""
        candidates = _build_candidates("timeout", "schedules")
        container_origins = [c for c in candidates if c[2] == "container"]
        assert len(container_origins) > 0, "Should have container-derived candidates"
        # The container "schedules" should produce at least one container-origin candidate
        container_names = {c[0] for c in container_origins}
        assert any("schedule" in name or "schedules" in name for name in container_names)

    def test_field_candidates_have_field_origin(self):
        """Field-name-derived candidates should have 'field' origin."""
        candidates = _build_candidates("timeout", "schedules")
        field_origins = [c for c in candidates if c[2] == "field"]
        assert len(field_origins) > 0, "Should have field-derived candidates"
        # "timeout" (the field) should be in field-derived set
        field_names = {c[0] for c in field_origins}
        assert "timeout" in field_names

    def test_fk_suffix_stripped_gets_field_origin(self):
        """FK suffix stripping produces field-origin candidates."""
        candidates = _build_candidates("user_id", None)
        field_origins = [c for c in candidates if c[2] == "field"]
        field_names = {c[0] for c in field_origins}
        assert "user" in field_names, "Stripped 'user' should be field-derived"

    def test_qualifiable_token_expansion_gets_field_origin(self):
        """Qualifiable token expansion (e.g., id + container) gets 'field' origin."""
        candidates = _build_candidates("id", "subnet")
        field_origins = [c for c in candidates if c[2] == "field"]
        field_names = {c[0] for c in field_origins}
        # "subnet__id" and "subnet" should be field-derived (field qualification)
        assert "subnet" in field_names or any("subnet" in n for n in field_names)

    def test_multi_word_container_produces_container_candidates(self):
        """Multi-word containers produce suffix subsequences with 'container' origin."""
        candidates = _build_candidates("timeout", "job-templates-schedules")
        container_origins = [c for c in candidates if c[2] == "container"]
        assert len(container_origins) >= 2, "Multi-word container should produce multiple candidates"


class TestInferTargetBehavioralParity:
    """Verify infer_target returns identical results after origin tracking."""

    _RESOURCES = frozenset({"schedules", "series", "users", "credentials", "ad-hoc-commands"})

    def test_series_id_unchanged(self):
        """series_id -> series should match identically."""
        target, conf = infer_target(
            "series_id", {"type": "integer"}, self._RESOURCES,
        )
        assert target == "series"
        assert conf > 0.0

    def test_timeout_with_container_unchanged(self):
        """timeout on schedules container should still match (penalty comes in section 02)."""
        target, conf = infer_target(
            "timeout", {"type": "integer"}, self._RESOURCES,
            container="schedules",
        )
        # Should still match schedules (section 02 adds the penalty)
        assert target == "schedules"
        assert conf > 0.0

    def test_user_id_unchanged(self):
        """user_id -> users should match identically."""
        target, conf = infer_target(
            "user_id", {"type": "integer"}, self._RESOURCES,
        )
        assert target == "users"
        assert conf > 0.0

    def test_credential_unchanged(self):
        """credential -> credentials should match identically."""
        target, conf = infer_target(
            "credential", {"type": "string"}, self._RESOURCES,
        )
        assert target == "credentials"
        assert conf > 0.0
