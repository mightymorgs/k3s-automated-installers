"""Tests for helm values walker (Stage 2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from idi.generation.helm.walker import walk_values, get_json_type


# ---------------------------------------------------------------------------
# Fixture path helper
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[5]
_SPECS_DIR = _REPO_ROOT / "catalog" / "specs" / "helm"


def _load_yaml(chart_name: str) -> dict:
    """Load a chart's values.yaml using ruamel.yaml safe loader."""
    from ruamel.yaml import YAML
    yaml = YAML(typ="safe")
    path = _SPECS_DIR / f"{chart_name}-values.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.load(f) or {}


# ---------------------------------------------------------------------------
# get_json_type
# ---------------------------------------------------------------------------

class TestGetJsonType:
    def test_string(self):
        assert get_json_type("hello") == "string"

    def test_boolean_true(self):
        assert get_json_type(True) == "boolean"

    def test_boolean_false(self):
        assert get_json_type(False) == "boolean"

    def test_integer(self):
        assert get_json_type(42) == "integer"

    def test_float(self):
        assert get_json_type(3.14) == "number"

    def test_list(self):
        assert get_json_type([1, 2, 3]) == "array"

    def test_none(self):
        assert get_json_type(None) == "null"

    def test_empty_dict(self):
        assert get_json_type({}) == "object"


# ---------------------------------------------------------------------------
# Basic walk tests
# ---------------------------------------------------------------------------

class TestWalkBasics:
    def test_flat_dict(self):
        facts = walk_values({"a": 1, "b": "x"})
        assert len(facts) == 2
        paths = {f.path for f in facts}
        assert "a" in paths
        assert "b" in paths

    def test_nested_dict(self):
        facts = walk_values({"a": {"b": 1}})
        assert len(facts) == 1
        assert facts[0].path_segments == ["a", "b"]
        assert facts[0].path == "a.b"

    def test_deeply_nested(self):
        facts = walk_values({"a": {"b": {"c": 1}}})
        assert len(facts) == 1
        assert facts[0].path_segments == ["a", "b", "c"]

    def test_array_is_leaf(self):
        facts = walk_values({"items": [1, 2, 3]})
        assert len(facts) == 1
        assert facts[0].type == "array"
        assert facts[0].default_value == [1, 2, 3]

    def test_array_of_objects_is_leaf(self):
        facts = walk_values({"items": [{"name": "x"}]})
        assert len(facts) == 1
        assert facts[0].type == "array"

    def test_empty_dict_is_leaf(self):
        facts = walk_values({"config": {}})
        assert len(facts) == 1
        assert facts[0].type == "object"

    def test_null_value(self):
        facts = walk_values({"key": None})
        assert len(facts) == 1
        assert facts[0].type == "null"

    def test_path_equals_joined_segments(self):
        facts = walk_values({"a": {"b": {"c": 1}}, "x": "y"})
        for f in facts:
            assert f.path == ".".join(f.path_segments)


# ---------------------------------------------------------------------------
# Template and default detection
# ---------------------------------------------------------------------------

class TestWalkDetection:
    def test_template_detected(self):
        facts = walk_values({"val": "{{ .Values.foo }}"})
        assert facts[0].has_template is True

    def test_no_template(self):
        facts = walk_values({"val": "plain"})
        assert facts[0].has_template is False

    def test_empty_string_is_default_empty(self):
        facts = walk_values({"val": ""})
        assert facts[0].default_empty is True

    def test_none_is_default_empty(self):
        facts = walk_values({"val": None})
        assert facts[0].default_empty is True

    def test_zero_is_not_default_empty(self):
        facts = walk_values({"val": 0})
        assert facts[0].default_empty is False

    def test_sentinel_dash(self):
        facts = walk_values({"val": "-"})
        assert facts[0].type == "string"
        assert facts[0].default_value == "-"
        assert facts[0].default_empty is False


# ---------------------------------------------------------------------------
# Format hints
# ---------------------------------------------------------------------------

class TestFormatHints:
    def test_hcl_format_hint(self):
        hcl_config = 'listener "tcp" {\n  address = "0.0.0.0:8200"\n}'
        facts = walk_values({"serverConfig": hcl_config})
        assert facts[0].format == "hcl"

    def test_yaml_format_hint(self):
        yaml_config = "key: value\nanother: thing\n"
        facts = walk_values({"appConfig": yaml_config})
        assert facts[0].format == "yaml"

    def test_non_config_key_no_format(self):
        facts = walk_values({"name": "some: value"})
        assert facts[0].format is None


# ---------------------------------------------------------------------------
# Dotted keys
# ---------------------------------------------------------------------------

class TestDottedKeys:
    def test_literal_dot_in_key(self):
        facts = walk_values({"podAnnotations": {"prometheus.io/scrape": "true"}})
        assert len(facts) == 1
        assert facts[0].path_segments == ["podAnnotations", "prometheus.io/scrape"]


# ---------------------------------------------------------------------------
# Large value truncation
# ---------------------------------------------------------------------------

class TestLargeValueTruncation:
    def test_large_value_truncated(self):
        big_value = "x" * 5000
        facts = walk_values({"big": big_value})
        assert facts[0].default_truncated is True
        assert len(str(facts[0].default_value)) < 5000

    def test_normal_value_not_truncated(self):
        facts = walk_values({"small": "hello"})
        assert facts[0].default_truncated is False


# ---------------------------------------------------------------------------
# Integration: real chart fixture
# ---------------------------------------------------------------------------

class TestWalkIntegration:
    def test_vault_produces_many_facts(self):
        values = _load_yaml("vault")
        facts = walk_values(values)
        assert len(facts) >= 100  # vault has 180+ leaf values
        # Every fact should have valid path_segments
        for f in facts:
            assert len(f.path_segments) > 0
            assert f.path == ".".join(f.path_segments)
