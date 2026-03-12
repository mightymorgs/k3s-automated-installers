"""Tests for lexical cohesion penalty in infer_target()."""
from __future__ import annotations

from idi.generation.dep_adapters.target_inference import infer_target


_RESOURCES = frozenset({
    "schedules", "series", "users", "credentials",
    "ad-hoc-commands", "instance-groups", "indexer",
})


class TestLexicalCohesionPenalty:
    """Container-derived matches with zero field↔target overlap are penalized."""

    def test_timeout_on_schedules_penalized(self):
        """timeout has zero overlap with schedules -> heavy penalty."""
        target, conf = infer_target(
            "timeout", {"type": "integer"}, _RESOURCES,
            container="schedules",
        )
        # After ×0.15 penalty, confidence should be well below body threshold (0.25)
        assert target == "schedules"
        assert conf < 0.10

    def test_forks_on_ad_hoc_commands_penalized(self):
        """forks has zero overlap with ad-hoc-commands -> penalized."""
        target, conf = infer_target(
            "forks", {"type": "integer"}, _RESOURCES,
            container="ad-hoc-commands",
        )
        assert conf < 0.10

    def test_max_concurrent_jobs_on_instance_groups_penalized(self):
        """max_concurrent_jobs has zero overlap with instance-groups."""
        target, conf = infer_target(
            "max_concurrent_jobs", {"type": "integer"}, _RESOURCES,
            container="instance-groups",
        )
        assert conf < 0.10

    def test_retention_on_indexer_penalized(self):
        """retention has zero overlap with indexer -> penalized."""
        target, conf = infer_target(
            "retention", {"type": "integer"}, _RESOURCES,
            container="indexer",
        )
        # indexer might or might not match — but if it does, should be penalized
        if target == "indexer":
            assert conf < 0.10


class TestLexicalCohesionPreservesTP:
    """Field-derived matches are never penalized."""

    def test_series_id_preserved(self):
        """series_id -> series is field-derived (FK suffix strip), no penalty."""
        target, conf = infer_target(
            "series_id", {"type": "integer"}, _RESOURCES,
        )
        assert target == "series"
        assert conf >= 0.25  # Above body threshold

    def test_user_id_preserved(self):
        """user_id -> users is field-derived, no penalty."""
        target, conf = infer_target(
            "user_id", {"type": "integer"}, _RESOURCES,
        )
        assert target == "users"
        assert conf >= 0.25

    def test_credential_preserved(self):
        """credential -> credentials: field-derived, not penalized.

        Note: plain string type_factor=0.5, so confidence is naturally low
        (0.7 * 0.5 * 0.5 = 0.175). The key assertion is that it's NOT
        further reduced by the lexical cohesion penalty.
        """
        target, conf = infer_target(
            "credential", {"type": "string"}, _RESOURCES,
        )
        assert target == "credentials"
        # Field-derived match — no lexical cohesion penalty applied.
        # 0.175 is the natural score (base 0.7 × match 0.5 × type 0.5).
        assert conf >= 0.15

    def test_series_id_with_container_preserved(self):
        """series_id with container still field-derived, no penalty."""
        target, conf = infer_target(
            "series_id", {"type": "integer"}, _RESOURCES,
            container="episodes",
        )
        assert target == "series"
        assert conf >= 0.25

    def test_schedule_id_on_schedules_preserved(self):
        """schedule_id on schedules endpoint: field-derived match via suffix strip."""
        target, conf = infer_target(
            "schedule_id", {"type": "integer"}, _RESOURCES,
            container="schedules",
        )
        assert target == "schedules"
        assert conf >= 0.25


class TestLexicalCohesionEdgeCases:
    """Edge cases for the lexical cohesion penalty."""

    def test_partial_overlap_no_penalty(self):
        """If field has some token overlap with target, no penalty."""
        # schedule_timeout has 'schedule' which overlaps with 'schedules'
        resources = frozenset({"schedules"})
        target, conf = infer_target(
            "schedule_timeout", {"type": "integer"}, resources,
            container="schedules",
        )
        if target == "schedules":
            # schedule stems to 'schedul', schedules also stems to 'schedul' -> overlap
            assert conf >= 0.10  # No heavy penalty

    def test_no_container_no_penalty(self):
        """Without container, no container-derived match, no penalty possible."""
        target, conf = infer_target(
            "timeout", {"type": "integer"}, _RESOURCES,
        )
        # Without container, timeout is unlikely to match anything
        # (no container candidates). If it does match, it's field-derived.
        if target is not None:
            assert conf >= 0.10
