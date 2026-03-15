"""Tests for helm schema loader (Stage 1 partial — Slice 1)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from idi.generation.helm.schema_loader import load_schema
from idi.generation.helm.models import SchemaInfo


@pytest.fixture
def tmp_schema(tmp_path: Path):
    """Helper that writes a schema dict to a temp JSON file and returns the path."""
    def _write(schema: dict) -> Path:
        p = tmp_path / "values.schema.json"
        p.write_text(json.dumps(schema), encoding="utf-8")
        return p
    return _write


# ---------------------------------------------------------------------------
# None / missing / malformed
# ---------------------------------------------------------------------------

class TestSchemaLoaderEdgeCases:
    def test_none_path_returns_empty(self):
        overrides, diag = load_schema(None)
        assert overrides == {}
        assert diag["ref_unresolved_count"] == 0
        assert diag["unsupported_keywords"] == []

    def test_nonexistent_path_returns_empty(self):
        overrides, diag = load_schema("/nonexistent/values.schema.json")
        assert overrides == {}
        assert diag["ref_unresolved_count"] == 0

    def test_malformed_json_logs_warning(self, tmp_path, caplog):
        bad = tmp_path / "values.schema.json"
        bad.write_text("{broken json", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            overrides, diag = load_schema(str(bad))
        assert overrides == {}
        assert any("malformed" in r.message.lower() or "json" in r.message.lower()
                    for r in caplog.records)

    def test_diagnostics_always_has_both_keys(self, tmp_schema):
        schema = {"type": "object", "properties": {}}
        overrides, diag = load_schema(str(tmp_schema(schema)))
        assert "ref_unresolved_count" in diag
        assert "unsupported_keywords" in diag


# ---------------------------------------------------------------------------
# Basic property extraction
# ---------------------------------------------------------------------------

class TestSchemaLoaderBasicProperties:
    def test_simple_string_property(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert ("name",) in overrides
        info = overrides[("name",)]
        assert info.type == "string"
        assert info.format is None
        assert info.enum is None
        assert info.required is False

    def test_format_password(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "secret": {"type": "string", "format": "password"}
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert overrides[("secret",)].format == "password"

    def test_write_only(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "key": {"type": "string", "writeOnly": True}
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert overrides[("key",)].write_only is True

    def test_enum(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["a", "b"]}
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert overrides[("mode",)].enum == ["a", "b"]

    def test_description_and_default(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "description": "Server port", "default": 8080}
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        info = overrides[("port",)]
        assert info.description == "Server port"
        assert info.default == 8080

    def test_pattern(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+\\.\\d+$"}
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert overrides[("ip",)].pattern is not None


# ---------------------------------------------------------------------------
# Nested objects and required
# ---------------------------------------------------------------------------

class TestSchemaLoaderNesting:
    def test_nested_object_recursive_walk(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "server": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"}
                    }
                }
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert ("server", "port") in overrides
        assert overrides[("server", "port")].type == "integer"

    def test_required_from_parent(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "server": {
                    "type": "object",
                    "required": ["port"],
                    "properties": {
                        "port": {"type": "integer"},
                        "host": {"type": "string"},
                    }
                }
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        assert overrides[("server", "port")].required is True
        assert overrides[("server", "host")].required is False

    def test_array_does_not_recurse_into_items(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "tolerations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"}
                        }
                    }
                }
            }
        }
        overrides, _ = load_schema(str(tmp_schema(schema)))
        # Should have tolerations entry but NOT tolerations.key
        assert ("tolerations",) in overrides
        assert overrides[("tolerations",)].type == "array"
        assert ("tolerations", "key") not in overrides


# ---------------------------------------------------------------------------
# $ref and unsupported keywords
# ---------------------------------------------------------------------------

class TestSchemaLoaderDiagnostics:
    def test_ref_logs_warning_and_counts(self, tmp_schema, caplog):
        schema = {
            "type": "object",
            "properties": {
                "config": {"$ref": "#/$defs/Config"}
            }
        }
        with caplog.at_level(logging.WARNING):
            overrides, diag = load_schema(str(tmp_schema(schema)))
        assert diag["ref_unresolved_count"] >= 1
        assert ("config",) not in overrides

    def test_if_then_else_logs_warning(self, tmp_schema, caplog):
        schema = {
            "type": "object",
            "if": {"properties": {"mode": {"const": "ha"}}},
            "then": {"required": ["replicas"]},
            "else": {},
            "properties": {
                "mode": {"type": "string"}
            }
        }
        with caplog.at_level(logging.WARNING):
            _, diag = load_schema(str(tmp_schema(schema)))
        assert "if" in diag["unsupported_keywords"]

    def test_oneOf_in_unsupported_keywords(self, tmp_schema):
        schema = {
            "type": "object",
            "properties": {
                "backend": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "integer"},
                    ]
                }
            }
        }
        _, diag = load_schema(str(tmp_schema(schema)))
        assert "oneOf" in diag["unsupported_keywords"]
