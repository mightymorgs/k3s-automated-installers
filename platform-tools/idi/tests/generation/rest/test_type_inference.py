"""Tests for type inference from sibling keys (#5)."""
from idi.generation.field_extractor import infer_schema_type


class TestTypeInference:
    def test_properties_inferred_as_object(self):
        schema = {"properties": {"name": {"type": "string"}}}
        result = infer_schema_type(schema)
        assert result["type"] == "object"

    def test_items_inferred_as_array(self):
        schema = {"items": {"type": "string"}}
        result = infer_schema_type(schema)
        assert result["type"] == "array"

    def test_enum_strings_inferred_as_string(self):
        schema = {"enum": ["a", "b", "c"]}
        result = infer_schema_type(schema)
        assert result["type"] == "string"

    def test_enum_integers_inferred_as_integer(self):
        schema = {"enum": [1, 2, 3]}
        result = infer_schema_type(schema)
        assert result["type"] == "integer"

    def test_enum_booleans_inferred_as_boolean(self):
        """bool must be checked before int since bool is subclass of int."""
        schema = {"enum": [True, False]}
        result = infer_schema_type(schema)
        assert result["type"] == "boolean"

    def test_explicit_type_unchanged(self):
        schema = {"type": "string", "properties": {"x": {}}}
        result = infer_schema_type(schema)
        assert result["type"] == "string"

    def test_no_type_inferring_siblings_unchanged(self):
        schema = {"description": "nothing here"}
        result = infer_schema_type(schema)
        assert "type" not in result

    def test_does_not_mutate_original(self):
        schema = {"properties": {"name": {"type": "string"}}}
        result = infer_schema_type(schema)
        assert "type" not in schema
        assert result["type"] == "object"
