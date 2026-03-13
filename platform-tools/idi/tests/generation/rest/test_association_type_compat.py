"""Tests for association shape detector + type compatibility (Section 05)."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency, OperationInfo
from idi.generation.dep_adapters.verify import (
    apply_type_compatibility_check,
    detect_association_indices,
    suppress_fan_out,
)


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


def _op(resource: str = "test", body_schema: dict | None = None) -> OperationInfo:
    return OperationInfo(
        service="svc", resource=resource, operation="create",
        path=f"/{resource}", method="POST",
        body_schema=body_schema or {},
        response_schema={},
        path_params=[], query_params=[],
    )


# ── Association Shape Detector ──────────────────────────────────────────


class TestAssociationDetector:
    """Detect association/join schemas to protect from fan-out suppression."""

    def test_two_fk_fields_different_targets_detected(self):
        """body with user_id + role_id matching different resources -> association."""
        deps = [
            _dep("user_id", "users"),
            _dep("role_id", "roles"),
        ]
        op = _op(body_schema={"properties": {
            "user_id": {"type": "integer"},
            "role_id": {"type": "integer"},
        }})
        identifier_index = {
            "users": {"id", "user_id"},
            "roles": {"id", "role_id"},
        }
        protected = detect_association_indices(deps, op, identifier_index)
        assert len(protected) == 2
        assert 0 in protected and 1 in protected

    def test_fk_suffixed_fields_detected_without_required(self):
        """FK-suffixed fields detected even without 'required' array."""
        deps = [
            _dep("user_id", "users"),
            _dep("group_id", "groups"),
            _dep("description", "groups"),
        ]
        op = _op(body_schema={"properties": {
            "user_id": {"type": "integer"},
            "group_id": {"type": "integer"},
            "description": {"type": "string"},
        }})
        identifier_index = {
            "users": {"id", "user_id"},
            "groups": {"id", "group_id"},
        }
        protected = detect_association_indices(deps, op, identifier_index)
        # user_id and group_id are protected (association shape)
        assert 0 in protected
        assert 1 in protected

    def test_single_fk_not_association(self):
        """body with single FK field -> NOT association."""
        deps = [
            _dep("user_id", "users"),
            _dep("timeout", "users"),
        ]
        op = _op(body_schema={"properties": {
            "user_id": {"type": "integer"},
            "timeout": {"type": "integer"},
        }})
        identifier_index = {
            "users": {"id", "user_id"},
        }
        protected = detect_association_indices(deps, op, identifier_index)
        assert len(protected) == 0

    def test_two_fields_same_target_not_association(self):
        """body with 2 fields matching SAME resource -> NOT association."""
        deps = [
            _dep("user_id", "users"),
            _dep("user_name", "users"),
        ]
        op = _op(body_schema={"properties": {
            "user_id": {"type": "integer"},
            "user_name": {"type": "string"},
        }})
        identifier_index = {
            "users": {"id", "user_id", "user_name"},
        }
        protected = detect_association_indices(deps, op, identifier_index)
        assert len(protected) == 0

    def test_association_protects_from_fan_out(self):
        """Protected indices are NOT penalized by fan-out suppression."""
        deps = [
            _dep("user_id", "target", confidence=0.6),
            _dep("role_id", "target", confidence=0.5),
            _dep("timeout", "target", confidence=0.4),
        ]
        protected = {0, 1}  # user_id and role_id are protected
        result = suppress_fan_out(deps, protected_indices=protected)
        # user_id and role_id should be unchanged
        assert result[0].confidence == 0.6  # Protected
        assert result[1].confidence == 0.5  # Protected
        # timeout is not protected and not FK-suffixed, but group
        # may still penalize if enough non-FK non-protected fields exist
        # With 3 edges, 2 protected, only 1 non-protected -> below threshold

    def test_no_body_schema_not_association(self):
        """Operation with no body schema -> not association."""
        deps = [_dep("user_id", "users")]
        op = _op()
        identifier_index = {"users": {"id"}}
        protected = detect_association_indices(deps, op, identifier_index)
        assert len(protected) == 0


# ── Type/Format Compatibility ───────────────────────────────────────────


class TestTypeCompatibility:
    """Type/format compatibility checking between consumer and target identifiers."""

    def test_integer_consumer_integer_target_compatible(self):
        """integer consumer + integer target identifier -> compatible."""
        deps = [_dep("user_id", "users", confidence=0.5)]
        identifier_type_index = {"users": {"id": ("integer", "")}}
        op = _op(body_schema={"properties": {
            "user_id": {"type": "integer"},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_string_consumer_uuid_target_compatible(self):
        """string consumer + string(uuid) target -> compatible."""
        deps = [_dep("user_id", "users", confidence=0.5)]
        identifier_type_index = {"users": {"id": ("string", "uuid")}}
        op = _op(body_schema={"properties": {
            "user_id": {"type": "string", "format": "uuid"},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_string_consumer_integer_target_penalized(self):
        """string consumer + only integer target identifiers -> penalty."""
        deps = [_dep("schedule_id", "schedules", confidence=0.5)]
        identifier_type_index = {"schedules": {"id": ("integer", "")}}
        op = _op(body_schema={"properties": {
            "schedule_id": {"type": "string", "format": "uuid"},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.1  # 0.5 * 0.2

    def test_integer_consumer_uuid_target_penalized(self):
        """integer consumer + only string(uuid) target identifiers -> penalty."""
        deps = [_dep("ref_id", "items", confidence=0.5)]
        identifier_type_index = {"items": {"id": ("string", "uuid")}}
        op = _op(body_schema={"properties": {
            "ref_id": {"type": "integer"},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.1  # 0.5 * 0.2

    def test_array_integer_consumer_compatible(self):
        """array of integers consumer + integer target -> compatible (unwrapped)."""
        deps = [_dep("user_ids", "users", confidence=0.5)]
        identifier_type_index = {"users": {"id": ("integer", "")}}
        op = _op(body_schema={"properties": {
            "user_ids": {"type": "array", "items": {"type": "integer"}},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_array_string_consumer_integer_target_penalized(self):
        """array of strings consumer + only integer target -> penalty."""
        deps = [_dep("tag_ids", "tags", confidence=0.5)]
        identifier_type_index = {"tags": {"id": ("integer", "")}}
        op = _op(body_schema={"properties": {
            "tag_ids": {"type": "array", "items": {"type": "string"}},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.1  # 0.5 * 0.2

    def test_no_type_info_conservative_pass(self):
        """No type info for target -> no penalty."""
        deps = [_dep("ref_id", "unknown", confidence=0.5)]
        identifier_type_index = {}
        op = _op(body_schema={"properties": {
            "ref_id": {"type": "integer"},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_no_consumer_type_conservative_pass(self):
        """No consumer type info -> no penalty."""
        deps = [_dep("ref_id", "users", confidence=0.5)]
        identifier_type_index = {"users": {"id": ("integer", "")}}
        op = _op(body_schema={"properties": {
            "ref_id": {},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_non_body_edges_exempt(self):
        """Non-body edges are not checked for type compatibility."""
        deps = [_dep("ref_id", "users", source="generic_odg:path", confidence=0.5)]
        identifier_type_index = {"users": {"id": ("string", "uuid")}}
        op = _op(body_schema={"properties": {
            "ref_id": {"type": "integer"},
        }})
        result = apply_type_compatibility_check(
            deps, identifier_type_index, op, {},
        )
        assert result[0].confidence == 0.5  # Unchanged
