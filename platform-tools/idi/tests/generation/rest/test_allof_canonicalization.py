"""Tests for allOf/oneOf/anyOf canonicalization in field_extractor.py."""
from __future__ import annotations

import pytest

from idi.generation.field_extractor import canonicalize_composed_schema


class TestAllOfMerge:
    """Test allOf property merging."""

    def test_allof_two_branches_merged(self):
        """allOf with two branches merges all properties into a flat schema."""
        schema = {
            "allOf": [
                {"properties": {"name": {"type": "string"}}, "required": ["name"]},
                {"properties": {"age": {"type": "integer"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert "name" in result["properties"]
        assert "age" in result["properties"]
        assert result["properties"]["name"]["type"] == "string"
        assert result["properties"]["age"]["type"] == "integer"
        assert "name" in result["required"]

    def test_allof_ref_plus_inline(self):
        """allOf with a resolved $ref schema + inline properties merges both."""
        # Simulates a pre-resolved $ref (already inline dict)
        schema = {
            "allOf": [
                {"properties": {"id": {"type": "string", "format": "uuid"}}},
                {"properties": {"role": {"type": "string", "enum": ["admin", "user"]}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert "id" in result["properties"]
        assert "role" in result["properties"]
        assert result["properties"]["id"]["format"] == "uuid"

    def test_allof_conflicting_property_types(self):
        """allOf with same property name but different types marks it ambiguous."""
        schema = {
            "allOf": [
                {"properties": {"value": {"type": "string"}}},
                {"properties": {"value": {"type": "integer"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert result["properties"]["value"]["_ambiguous"] is True

    def test_allof_preserves_discriminator(self):
        """Discriminator field is preserved during allOf merge."""
        schema = {
            "discriminator": {"propertyName": "type"},
            "allOf": [
                {"properties": {"type": {"type": "string"}}},
                {"properties": {"name": {"type": "string"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert "discriminator" in result
        assert result["discriminator"]["propertyName"] == "type"

    def test_allof_preserves_readonly_writeonly_last_wins(self):
        """readOnly/writeOnly are preserved with last-wins semantics."""
        schema = {
            "allOf": [
                {"properties": {"x": {"type": "string", "readOnly": False}}},
                {"properties": {"x": {"type": "string", "readOnly": True}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert result["properties"]["x"]["readOnly"] is True
        # Same type, so not ambiguous
        assert "_ambiguous" not in result["properties"]["x"]

    def test_allof_required_fields_merged(self):
        """required lists from all allOf branches are merged and deduplicated."""
        schema = {
            "allOf": [
                {"required": ["a", "b"], "properties": {"a": {"type": "string"}, "b": {"type": "string"}}},
                {"required": ["b", "c"], "properties": {"c": {"type": "string"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert sorted(result["required"]) == ["a", "b", "c"]

    def test_allof_empty_branches(self):
        """allOf with no branches returns schema as-is."""
        schema = {"allOf": []}
        result = canonicalize_composed_schema(schema)
        # Should return without error; no properties expected
        assert result.get("properties", {}) == {}

    def test_allof_nested_recursively_flattened(self):
        """Nested allOf (allOf within allOf) is recursively flattened."""
        schema = {
            "allOf": [
                {
                    "allOf": [
                        {"properties": {"a": {"type": "string"}}},
                        {"properties": {"b": {"type": "integer"}}},
                    ],
                },
                {"properties": {"c": {"type": "boolean"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert "a" in result["properties"]
        assert "b" in result["properties"]
        assert "c" in result["properties"]


    def test_allof_with_parent_properties(self):
        """Properties alongside allOf are included in the merge."""
        schema = {
            "type": "object",
            "properties": {"base": {"type": "string"}},
            "allOf": [
                {"properties": {"ext": {"type": "integer"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert "base" in result["properties"]
        assert "ext" in result["properties"]


class TestOneOfAnyOf:
    """Test oneOf/anyOf intersection semantics."""

    def test_oneof_intersection_high_confidence(self):
        """oneOf returns intersection of properties across all branches."""
        schema = {
            "oneOf": [
                {"properties": {"id": {"type": "string"}, "name": {"type": "string"}, "email": {"type": "string"}}},
                {"properties": {"id": {"type": "string"}, "name": {"type": "string"}, "phone": {"type": "string"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        # Intersection: id, name
        assert "id" in result["properties"]
        assert "name" in result["properties"]
        # Not in intersection
        assert "email" not in result["properties"]
        assert "phone" not in result["properties"]

    def test_oneof_with_discriminator_allows_union(self):
        """oneOf with discriminator allows union of all properties."""
        schema = {
            "discriminator": {"propertyName": "type"},
            "oneOf": [
                {"properties": {"type": {"type": "string"}, "name": {"type": "string"}}},
                {"properties": {"type": {"type": "string"}, "email": {"type": "string"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        # Union: type, name, email
        assert "type" in result["properties"]
        assert "name" in result["properties"]
        assert "email" in result["properties"]

    def test_anyof_intersection_high_confidence(self):
        """anyOf returns intersection of properties for high-confidence."""
        schema = {
            "anyOf": [
                {"properties": {"id": {"type": "string"}, "title": {"type": "string"}}},
                {"properties": {"id": {"type": "string"}, "body": {"type": "string"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert "id" in result["properties"]
        assert "title" not in result["properties"]
        assert "body" not in result["properties"]


class TestCircularRefProtection:
    """Test circular $ref cycle detection."""

    def test_circular_ref_halts_recursion(self):
        """Circular $ref in composed schema detected via visited set, no infinite loop."""
        # Create a self-referencing schema via object identity
        inner = {"type": "object", "properties": {"name": {"type": "string"}}}
        # Make it circular: inner's manager allOf references inner itself
        inner["properties"]["manager"] = {"allOf": [inner]}

        result = canonicalize_composed_schema(inner)
        # Should terminate without infinite loop
        assert "name" in result.get("properties", {})


class TestNoComposition:
    """Test schemas without composition keywords."""

    def test_plain_schema_returned_unchanged(self):
        """Schema without allOf/oneOf/anyOf is returned as-is."""
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = canonicalize_composed_schema(schema)
        assert result == schema

    def test_empty_schema_returned(self):
        """Empty schema dict returned as-is."""
        result = canonicalize_composed_schema({})
        assert result == {}


class TestTypeInference:
    """Test type is set to object when properties exist but type missing."""

    def test_type_inferred_as_object(self):
        """Merged result with properties but no type gets type=object."""
        schema = {
            "allOf": [
                {"properties": {"id": {"type": "string"}}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert result.get("type") == "object"


class TestAdditionalProperties:
    """Test additionalProperties handling."""

    def test_additional_properties_preserved(self):
        """additionalProperties from any branch is preserved."""
        schema = {
            "allOf": [
                {"properties": {"id": {"type": "string"}}},
                {"additionalProperties": {"type": "string"}},
            ],
        }
        result = canonicalize_composed_schema(schema)
        assert result["additionalProperties"] == {"type": "string"}


class TestIntegrationWithExtractSchemaFields:
    """Test that canonicalization integrates with extract_schema_fields."""

    def test_extract_schema_fields_uses_canonicalization(self):
        """extract_schema_fields() applies canonicalization before walking properties."""
        from unittest.mock import MagicMock

        from idi.generation.field_extractor import extract_schema_fields

        ctx = MagicMock()
        ctx.schema = {"paths": {}}

        # Schema with allOf that would previously miss properties
        schema = {
            "allOf": [
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                    },
                    "required": ["id"],
                },
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                },
            ],
        }
        result = extract_schema_fields(ctx, schema)
        assert "id" in result["properties"]
        assert "name" in result["properties"]
        assert "email" in result["properties"]
        assert "id" in result["required"]
