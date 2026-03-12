"""Tests for single-item combinator unwrapping (#3)."""
from idi.generation.field_extractor import unwrap_single_item_combinator


class TestSingleItemCombinatorUnwrap:
    def test_allof_single_ref_unwrapped(self):
        schema = {"allOf": [{"type": "object", "properties": {"id": {"type": "string"}}}]}
        result = unwrap_single_item_combinator(schema)
        assert result["type"] == "object"
        assert "id" in result["properties"]
        assert "allOf" not in result

    def test_oneof_single_schema_unwrapped(self):
        schema = {"oneOf": [{"type": "string"}]}
        result = unwrap_single_item_combinator(schema)
        assert result["type"] == "string"
        assert "oneOf" not in result

    def test_anyof_single_schema_unwrapped(self):
        schema = {"anyOf": [{"type": "integer"}]}
        result = unwrap_single_item_combinator(schema)
        assert result["type"] == "integer"
        assert "anyOf" not in result

    def test_allof_multiple_items_not_unwrapped(self):
        schema = {"allOf": [{"type": "object"}, {"type": "object"}]}
        result = unwrap_single_item_combinator(schema)
        assert "allOf" in result
        assert len(result["allOf"]) == 2

    def test_nested_single_item_recursively_unwrapped(self):
        schema = {"allOf": [{"oneOf": [{"type": "string"}]}]}
        result = unwrap_single_item_combinator(schema)
        assert result["type"] == "string"
        assert "allOf" not in result
        assert "oneOf" not in result

    def test_parent_metadata_preserved(self):
        schema = {
            "description": "Outer description",
            "title": "Outer title",
            "allOf": [{"type": "object", "properties": {"x": {"type": "int"}}}],
        }
        result = unwrap_single_item_combinator(schema)
        assert result["description"] == "Outer description"
        assert result["title"] == "Outer title"
        assert result["type"] == "object"

    def test_child_metadata_takes_precedence(self):
        schema = {
            "description": "Outer",
            "allOf": [{"type": "object", "description": "Inner"}],
        }
        result = unwrap_single_item_combinator(schema)
        assert result["description"] == "Inner"

    def test_non_combinator_schema_unchanged(self):
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        result = unwrap_single_item_combinator(schema)
        assert result == schema
