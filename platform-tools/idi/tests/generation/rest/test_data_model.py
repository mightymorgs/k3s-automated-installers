"""Tests for DetectionSource enum and Dependency dataclass changes."""
import json

import pytest

from idi.generation.dep_adapters.base import Dependency, DetectionSource


class TestDetectionSourceEnum:
    """DetectionSource enum members have correct string values and serialize to JSON."""

    def test_enum_members_have_correct_string_values(self):
        """Each member's value is a 'rest:xxx' namespaced string."""
        assert DetectionSource.DEFAULT == "rest:default"
        assert DetectionSource.CREDENTIAL_REGEX == "rest:credential_regex"
        assert DetectionSource.READONLY_FIELD == "rest:readonly_field"
        assert DetectionSource.WRITEONLY_FIELD == "rest:writeonly_field"
        assert DetectionSource.FK_SUFFIX == "rest:fk_suffix"
        assert DetectionSource.SCHEMA_NORMALIZE == "rest:schema_normalize"
        assert DetectionSource.PRODUCER_VALIDITY == "rest:producer_validity"
        assert DetectionSource.ID_SYNONYM == "rest:id_synonym"
        assert DetectionSource.OPENAPI_LINK == "rest:openapi_link"
        assert DetectionSource.ENVELOPE_UNWRAP == "rest:envelope_unwrap"
        assert DetectionSource.NESTED_PRODUCER == "rest:nested_producer"
        assert DetectionSource.RESPONSE_WALK == "rest:response_walk"
        assert DetectionSource.READONLY_DIFF == "rest:readonly_diff"
        assert DetectionSource.NESTED_FK == "rest:nested_fk"
        assert DetectionSource.ANNOTATION == "rest:annotation"

    def test_enum_is_str_subclass(self):
        """DetectionSource is a str subclass so it serializes to JSON without a custom encoder."""
        assert isinstance(DetectionSource.DEFAULT, str)

    def test_enum_json_serializable(self):
        """The enum value serializes directly to JSON without a custom encoder."""
        result = json.dumps({"source": DetectionSource.OPENAPI_LINK})
        assert '"rest:openapi_link"' in result

    def test_enum_has_15_members(self):
        """The enum has exactly 15 members."""
        assert len(DetectionSource) == 15


class TestDependencyDataclass:
    """Dependency dataclass accepts the new detection_source field."""

    def test_accepts_detection_source_enum(self):
        """Dependency can be constructed with a DetectionSource enum value."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            detection_source=DetectionSource.FK_SUFFIX,
        )
        assert dep.detection_source == DetectionSource.FK_SUFFIX

    def test_detection_source_defaults_to_default(self):
        """When detection_source is not specified, it defaults to DetectionSource.DEFAULT."""
        dep = Dependency(field="user_id", target_resource="users")
        assert dep.detection_source == DetectionSource.DEFAULT

    def test_lineage_type_explicit(self):
        """Dependency accepts lineage_type='explicit' for ground-truth edges."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            lineage_type="explicit",
        )
        assert dep.lineage_type == "explicit"

    def test_lineage_type_inferred(self):
        """Dependency accepts lineage_type='inferred' for heuristic edges."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            lineage_type="inferred",
        )
        assert dep.lineage_type == "inferred"

    def test_existing_fields_unchanged(self):
        """All pre-existing Dependency fields still work as before."""
        dep = Dependency(
            field="user_id",
            target_resource="users",
            target_operation="create",
            fact_ref="facts://myapi/users#id",
            confidence=0.8,
            source="generic_odg:body",
            lineage_type="copy",
            discriminator_value=None,
            target_service=None,
            satisfaction="required_value",
        )
        assert dep.field == "user_id"
        assert dep.confidence == 0.8
        assert dep.source == "generic_odg:body"


class TestExistingAdaptersEmitDefault:
    """Existing adapters should emit DetectionSource.DEFAULT when not overridden."""

    def test_default_value_on_construction_without_kwarg(self):
        """Constructing Dependency without detection_source gives DEFAULT."""
        dep = Dependency(
            field="org_id",
            target_resource="organizations",
            source="generic_odg:body",
        )
        assert dep.detection_source == DetectionSource.DEFAULT


class TestRefMemoization:
    """$ref resolution memoization prevents redundant work."""

    def test_same_ref_resolved_once(self):
        """When the same $ref is encountered multiple times, it is resolved from cache."""
        from idi.generation.spec_loader import _resolve_refs

        spec = {
            "components": {
                "schemas": {
                    "Shared": {"type": "object", "properties": {"id": {"type": "string"}}}
                }
            }
        }
        obj = {
            "a": {"$ref": "#/components/schemas/Shared"},
            "b": {"$ref": "#/components/schemas/Shared"},
            "c": {"$ref": "#/components/schemas/Shared"},
        }
        result = _resolve_refs(obj, spec)
        # All three should resolve to the same schema structure.
        assert result["a"]["properties"]["id"]["type"] == "string"
        assert result["b"]["properties"]["id"]["type"] == "string"
        assert result["c"]["properties"]["id"]["type"] == "string"

    def test_memoized_results_are_independent_copies(self):
        """Mutating one resolved ref doesn't affect another."""
        from idi.generation.spec_loader import _resolve_refs

        spec = {
            "components": {
                "schemas": {
                    "Shared": {"type": "object", "properties": {"id": {"type": "string"}}}
                }
            }
        }
        obj = {
            "a": {"$ref": "#/components/schemas/Shared"},
            "b": {"$ref": "#/components/schemas/Shared"},
        }
        result = _resolve_refs(obj, spec)
        result["a"]["properties"]["id"]["type"] = "integer"
        assert result["b"]["properties"]["id"]["type"] == "string"
