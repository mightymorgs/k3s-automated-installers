"""Tests for co-occurrence fan-out suppression in verify.py."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency
from idi.generation.dep_adapters.verify import suppress_fan_out


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


class TestFanOutSuppression:
    """Penalize non-FK-suffixed fields when 3+ point to same target."""

    def test_three_non_fk_all_penalized(self):
        """3 fields without FK suffixes -> all penalized."""
        deps = [
            _dep("timeout", "schedules"),
            _dep("forks", "schedules"),
            _dep("job_slice_count", "schedules"),
        ]
        result = suppress_fan_out(deps)
        assert len(result) == 3
        for d in result:
            assert d.confidence < 0.15  # 0.5 * 0.2 = 0.1

    def test_three_fk_none_penalized(self):
        """3 fields with FK suffixes -> none penalized."""
        deps = [
            _dep("primary_user_id", "users"),
            _dep("secondary_user_id", "users"),
            _dep("reviewer_id", "users"),
        ]
        result = suppress_fan_out(deps)
        assert len(result) == 3
        for d in result:
            assert d.confidence == 0.5  # Unchanged

    def test_mixed_only_non_fk_penalized(self):
        """1 FK, 2 non-FK -> penalize only non-FK fields."""
        deps = [
            _dep("credential_id", "target", confidence=0.6),
            _dep("timeout", "target", confidence=0.5),
            _dep("forks", "target", confidence=0.5),
        ]
        result = suppress_fan_out(deps)
        # credential_id has FK suffix -> preserved
        cred = next(d for d in result if d.field == "credential_id")
        assert cred.confidence == 0.6
        # timeout and forks penalized
        timeout = next(d for d in result if d.field == "timeout")
        assert timeout.confidence < 0.15
        forks = next(d for d in result if d.field == "forks")
        assert forks.confidence < 0.15

    def test_two_fields_no_suppression(self):
        """Fewer than 3 fields -> no suppression."""
        deps = [
            _dep("timeout", "schedules"),
            _dep("forks", "schedules"),
        ]
        result = suppress_fan_out(deps)
        for d in result:
            assert d.confidence == 0.5

    def test_exact_50_percent_no_suppression(self):
        """4 fields, 2 FK + 2 non-FK (exactly 50%) -> no penalty (conservative)."""
        deps = [
            _dep("user_id", "target"),
            _dep("group_id", "target"),
            _dep("timeout", "target"),
            _dep("forks", "target"),
        ]
        result = suppress_fan_out(deps)
        for d in result:
            assert d.confidence == 0.5  # No change

    def test_non_body_sources_excluded(self):
        """Non-body sources are not included in grouping."""
        deps = [
            _dep("timeout", "schedules", source="generic_odg:path"),
            _dep("forks", "schedules", source="generic_odg:path"),
            _dep("priority", "schedules", source="generic_odg:path"),
        ]
        result = suppress_fan_out(deps)
        for d in result:
            assert d.confidence == 0.5  # No change — path source excluded

    def test_multiple_groups_independent(self):
        """Each target group is handled independently."""
        deps = [
            # Group A: 3 non-FK -> target1 (penalized)
            _dep("timeout", "target1"),
            _dep("forks", "target1"),
            _dep("priority", "target1"),
            # Group B: 2 non-FK -> target2 (NOT penalized — < 3)
            _dep("timeout", "target2"),
            _dep("forks", "target2"),
        ]
        result = suppress_fan_out(deps)
        target1_deps = [d for d in result if d.target_resource == "target1"]
        target2_deps = [d for d in result if d.target_resource == "target2"]
        # Group A: penalized
        for d in target1_deps:
            assert d.confidence < 0.15
        # Group B: unchanged
        for d in target2_deps:
            assert d.confidence == 0.5

    def test_mixed_sources_only_body_grouped(self):
        """Only body-source deps counted in groups; others pass through."""
        deps = [
            _dep("timeout", "schedules", source="generic_odg:body"),
            _dep("forks", "schedules", source="generic_odg:body"),
            _dep("priority", "schedules", source="generic_odg:body"),
            _dep("schedule_id", "schedules", source="generic_odg:path"),
        ]
        result = suppress_fan_out(deps)
        # Body deps penalized (3 non-FK -> same target)
        body_deps = [d for d in result if d.source == "generic_odg:body"]
        for d in body_deps:
            assert d.confidence < 0.15
        # Path dep unchanged
        path_dep = next(d for d in result if d.source == "generic_odg:path")
        assert path_dep.confidence == 0.5
