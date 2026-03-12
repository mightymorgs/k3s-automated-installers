"""Tests for identifier reference validation gate in verify.py."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency
from idi.generation.dep_adapters.verify import apply_identifier_validation


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


class TestIdentifierValidationFP:
    """False positive suppression: field doesn't match target identifiers."""

    def test_timeout_not_identifier(self):
        """timeout doesn't match schedules identifiers -> penalized."""
        deps = [_dep("timeout", "schedules")]
        index = {"schedules": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert len(result) == 1
        assert result[0].confidence == 0.05  # 0.5 * 0.1

    def test_forks_not_identifier(self):
        """forks doesn't match schedules identifiers -> penalized."""
        deps = [_dep("forks", "schedules", confidence=0.6)]
        index = {"schedules": {"id", "schedule_id"}}
        result = apply_identifier_validation(deps, index)
        assert len(result) == 1
        assert result[0].confidence == 0.06  # 0.6 * 0.1


class TestIdentifierValidationTP:
    """True positive preservation: field matches target identifiers."""

    def test_exact_match_series_id(self):
        """series_id matches series identifiers exactly."""
        deps = [_dep("series_id", "series")]
        index = {"series": {"id", "series_id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_exact_match_id(self):
        """id field matches identifiers."""
        deps = [_dep("id", "users")]
        index = {"users": {"id", "user_id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_normalized_match_credential(self):
        """credential matches via FK suffix stripping.

        dep field = 'credential', target = 'credentials'
        identifier 'credential_id' stripped = 'credential' -> match
        """
        deps = [_dep("credential", "credentials")]
        index = {"credentials": {"id", "credential_id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_normalized_match_user_id(self):
        """user_id exact match against identifier set."""
        deps = [_dep("user_id", "users")]
        index = {"users": {"id", "user_id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_stemmed_match(self):
        """credential_ref matches via stem comparison.

        dep field = 'credential_ref', stripped = 'credential'
        identifier 'credential' in set -> exact match on stripped form
        """
        deps = [_dep("credential_ref", "credentials")]
        index = {"credentials": {"credential"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5


class TestIdentifierValidationConservative:
    """Conservative behavior: pass when validation can't be done."""

    def test_target_not_in_index(self):
        """Target not in index -> pass (conservative)."""
        deps = [_dep("timeout", "unknown_resource")]
        index = {"schedules": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_empty_identifier_set(self):
        """Target exists in index but has no identifiers -> pass."""
        deps = [_dep("timeout", "schedules")]
        index = {"schedules": set()}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_none_index(self):
        """None identifier_index -> all pass."""
        deps = [_dep("timeout", "schedules")]
        result = apply_identifier_validation(deps, None)
        assert result[0].confidence == 0.5  # Unchanged


class TestIdentifierValidationGenericIds:
    """Generic identifiers always pass regardless of target."""

    def test_generic_id_passes(self):
        """'id' is a generic identifier -> always passes."""
        deps = [_dep("id", "users")]
        index = {"users": {"slug"}}  # 'id' not in identifiers, but is generic
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_generic_uuid_passes(self):
        deps = [_dep("uuid", "users")]
        index = {"users": {"slug"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_generic_slug_passes(self):
        deps = [_dep("slug", "items")]
        index = {"items": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_generic_name_passes(self):
        deps = [_dep("name", "resources")]
        index = {"resources": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_generic_pk_passes(self):
        deps = [_dep("pk", "items")]
        index = {"items": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_generic_key_passes(self):
        deps = [_dep("key", "items")]
        index = {"items": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5


class TestIdentifierValidationSourceFiltering:
    """Only body sources are validated; others pass through."""

    def test_path_source_excluded(self):
        """Path-sourced deps are not validated."""
        deps = [_dep("timeout", "schedules", source="generic_odg:path")]
        index = {"schedules": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Unchanged

    def test_link_source_excluded(self):
        deps = [_dep("timeout", "schedules", source="openapi_links")]
        index = {"schedules": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5

    def test_operationid_source_excluded(self):
        deps = [_dep("timeout", "schedules", source="generic_odg:operationid")]
        index = {"schedules": {"id"}}
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5


class TestIdentifierValidationMixed:
    """Mixed dep lists: only body deps without matching identifiers penalized."""

    def test_mixed_deps(self):
        """Only body deps with non-matching identifiers are penalized."""
        deps = [
            _dep("series_id", "series", confidence=0.6),   # Matches -> pass
            _dep("timeout", "schedules", confidence=0.5),   # No match -> penalize
            _dep("org_id", "orgs", source="generic_odg:path", confidence=0.7),  # Not body -> pass
        ]
        index = {"series": {"id", "series_id"}, "schedules": {"id"}}
        result = apply_identifier_validation(deps, index)
        series_dep = next(d for d in result if d.field == "series_id")
        timeout_dep = next(d for d in result if d.field == "timeout")
        org_dep = next(d for d in result if d.field == "org_id")
        assert series_dep.confidence == 0.6   # Unchanged
        assert timeout_dep.confidence == 0.05  # 0.5 * 0.1
        assert org_dep.confidence == 0.7       # Unchanged (not body)
