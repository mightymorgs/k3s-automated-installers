"""Tests for helm annotation parser (Stage 1 — Slices 1 & 2)."""
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
        lines = [f"# c{i}" for i in range(11)] + ["key: val"]
        key = find_next_yaml_key(lines, 0, 0)
        assert key is None

    def test_finds_key_at_same_indent(self):
        lines = ["  key: value"]
        key = find_next_yaml_key(lines, 0, 2)
        assert key == "key"


# ---------------------------------------------------------------------------
# Slice 2: Enhanced annotations
# ---------------------------------------------------------------------------

class TestMultiLineParam:
    def test_continuation_lines(self):
        text = (
            "## @param auth.password [string] Password for the database\n"
            "## This is a longer description\n"
            "## that continues\n"
            "auth:\n"
            "  password: \"\"\n"
        )
        result, _ = parse_annotations(text, {("auth", "password")})
        assert ("auth", "password") in result
        desc = result[("auth", "password")].description
        assert "Password for the database" in desc
        assert "longer description" in desc

    def test_continuation_stops_at_next_param(self):
        text = (
            "## @param auth.user [string] Username\n"
            "## @param auth.password [string] Password\n"
            "auth:\n"
            "  user: admin\n"
            "  password: \"\"\n"
        )
        result, _ = parse_annotations(text, {("auth", "user"), ("auth", "password")})
        assert result[("auth", "user")].description == "Username"
        assert result[("auth", "password")].description == "Password"

    def test_single_line_still_works(self):
        text = "## @param name [string] Simple\nname: val\n"
        result, _ = parse_annotations(text, {("name",)})
        assert result[("name",)].description == "Simple"


class TestHelmDocsTypeExpansion:
    def test_string_array(self):
        text = "# -- (string[]) List of names\nnames: []\n"
        result, _ = parse_annotations(text, {("names",)})
        assert result[("names",)].type == "array"

    def test_int_or_string(self):
        text = "# -- (int|string) Port or name\nport: 8080\n"
        result, _ = parse_annotations(text, {("port",)})
        assert result[("port",)].type == "string"

    def test_bool(self):
        text = "# -- (bool) Enable feature\nenabled: true\n"
        result, _ = parse_annotations(text, {("enabled",)})
        assert result[("enabled",)].type == "boolean"

    def test_list(self):
        text = "# -- (list) Items\nitems: []\n"
        result, _ = parse_annotations(text, {("items",)})
        assert result[("items",)].type == "array"

    def test_object(self):
        text = "# -- (object) Config map\nconfig: {}\n"
        result, _ = parse_annotations(text, {("config",)})
        assert result[("config",)].type == "object"

    def test_int_normalized(self):
        text = "# -- (int) Replica count\nreplicas: 1\n"
        result, _ = parse_annotations(text, {("replicas",)})
        assert result[("replicas",)].type == "integer"


class TestFindNextYamlKeyEnhanced:
    def test_key_3_lines_after_with_comments(self):
        lines = ["# comment 1", "# comment 2", "# comment 3", "mykey: value"]
        key = find_next_yaml_key(lines, 0, 0)
        assert key == "mykey"

    def test_key_beyond_max_distance_returns_none(self):
        # 11 comment lines then a key => should be beyond max lookahead (10)
        lines = [f"# comment {i}" for i in range(11)] + ["key: val"]
        key = find_next_yaml_key(lines, 0, 0)
        assert key is None


class TestNLPPatterns:
    def test_password_credential(self):
        from idi.generation.helm.classifier import match_description_patterns
        assert match_description_patterns("The password for the database") == "credential"

    def test_reference_identity(self):
        from idi.generation.helm.classifier import match_description_patterns
        assert match_description_patterns("Reference to an existing ConfigMap") == "identity"

    def test_url_addressability(self):
        from idi.generation.helm.classifier import match_description_patterns
        assert match_description_patterns("The URL of the service endpoint") == "addressability"

    def test_no_match_returns_none(self):
        from idi.generation.helm.classifier import match_description_patterns
        assert match_description_patterns("Number of replicas") is None

    def test_case_insensitive(self):
        from idi.generation.helm.classifier import match_description_patterns
        assert match_description_patterns("THE PASSWORD") == "credential"
