"""Tests for helm annotation parser (Stage 1 partial — Slice 1)."""
from __future__ import annotations

import pytest

from idi.generation.helm.annotations import parse_annotations, find_next_yaml_key


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestAnnotationsEdgeCases:
    def test_empty_text_returns_empty(self):
        result, skipped = parse_annotations("", set())
        assert result == {}
        assert skipped == 0

    def test_no_annotations_returns_empty(self):
        text = "server:\n  port: 8080\n"
        result, skipped = parse_annotations(text, {("server", "port")})
        assert result == {}
        assert skipped == 0

    def test_annotation_for_invalid_path_is_skipped(self):
        text = "## @param missing.key [string] A value\nmissing:\n  key: val\n"
        result, skipped = parse_annotations(text, set())
        assert result == {}
        assert skipped == 1


# ---------------------------------------------------------------------------
# @param parsing
# ---------------------------------------------------------------------------

class TestBitnamiParam:
    def test_single_param(self):
        text = "## @param name [string] The name\nname: myapp\n"
        result, _ = parse_annotations(text, {("name",)})
        assert ("name",) in result
        info = result[("name",)]
        assert info.type == "string"
        assert info.description == "The name"
        assert info.source == "bitnami_param"

    def test_nested_path(self):
        text = "## @param auth.password [string] The password\nauth:\n  password: \"\"\n"
        result, _ = parse_annotations(text, {("auth", "password")})
        assert ("auth", "password") in result

    def test_deep_nested_path(self):
        text = "## @param a.b.c [integer] Deep value\na:\n  b:\n    c: 42\n"
        result, _ = parse_annotations(text, {("a", "b", "c")})
        assert ("a", "b", "c") in result
        assert result[("a", "b", "c")].type == "integer"

    def test_multiple_params(self):
        text = (
            "## @param server.port [integer] Server port\n"
            "## @param server.host [string] Server host\n"
            "server:\n  port: 8080\n  host: localhost\n"
        )
        valid = {("server", "port"), ("server", "host")}
        result, _ = parse_annotations(text, valid)
        assert ("server", "port") in result
        assert ("server", "host") in result


# ---------------------------------------------------------------------------
# @schema parsing
# ---------------------------------------------------------------------------

class TestDadavSchema:
    def test_schema_type_and_description(self):
        text = (
            "# @schema type: string\n"
            "# @schema description: Service type\n"
            "type: ClusterIP\n"
        )
        result, _ = parse_annotations(text, {("type",)})
        assert ("type",) in result
        info = result[("type",)]
        assert info.type == "string"
        assert info.description == "Service type"
        assert info.source == "dadav_schema"

    def test_schema_enum(self):
        text = (
            '# @schema type: string\n'
            '# @schema enum: ["ClusterIP", "NodePort", "LoadBalancer"]\n'
            "type: ClusterIP\n"
        )
        result, _ = parse_annotations(text, {("type",)})
        assert result[("type",)].enum == ["ClusterIP", "NodePort", "LoadBalancer"]


# ---------------------------------------------------------------------------
# helm-docs parsing
# ---------------------------------------------------------------------------

class TestHelmDocs:
    def test_with_type_and_description(self):
        text = "# -- (string) Override the full name\nfullnameOverride: \"\"\n"
        result, _ = parse_annotations(text, {("fullnameOverride",)})
        assert ("fullnameOverride",) in result
        info = result[("fullnameOverride",)]
        assert info.type == "string"
        assert info.description == "Override the full name"
        assert info.source == "helm_docs"

    def test_description_only(self):
        text = "# -- Some description here\nname: value\n"
        result, _ = parse_annotations(text, {("name",)})
        assert ("name",) in result
        info = result[("name",)]
        assert info.type is None
        assert info.description == "Some description here"


# ---------------------------------------------------------------------------
# find_next_yaml_key
# ---------------------------------------------------------------------------

class TestFindNextYamlKey:
    def test_skips_blank_and_comment_lines(self):
        lines = ["# comment", "", "  # another comment", "mykey: value"]
        key = find_next_yaml_key(lines, 0, 0)
        assert key == "mykey"

    def test_returns_none_for_array_item(self):
        lines = ["  - name: foo"]
        key = find_next_yaml_key(lines, 0, 0)
        assert key is None

    def test_returns_none_when_key_too_far(self):
        lines = ["# c1", "# c2", "# c3", "# c4", "# c5", "# c6", "key: val"]
        key = find_next_yaml_key(lines, 0, 0)
        assert key is None

    def test_finds_key_at_same_indent(self):
        lines = ["  key: value"]
        key = find_next_yaml_key(lines, 0, 2)
        assert key == "key"
