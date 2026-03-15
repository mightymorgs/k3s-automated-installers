"""Tests for helm URI generation (Stage 5)."""
from __future__ import annotations

import pytest

from idi.generation.helm.uri import build_uri, decode_segment, encode_segment, generate_uris
from idi.generation.helm.models import HelmFact
from idi.generation.helm.walker import walk_values


class TestEncodeSegment:
    def test_plain_key(self):
        assert encode_segment("port") == "port"

    def test_dotted_key(self):
        assert encode_segment("prometheus.io/scrape") == "prometheus%2Eio%2Fscrape"

    def test_hash_key(self):
        assert encode_segment("my#key") == "my%23key"

    def test_percent(self):
        assert encode_segment("100%") == "100%25"

    def test_space(self):
        assert encode_segment("hello world") == "hello%20world"

    def test_double_encoding_prevented(self):
        # "%2E" in input should become "%252E" (the % gets encoded)
        assert encode_segment("%2E") == "%252E"


class TestDecodeSegment:
    def test_dotted(self):
        assert decode_segment("prometheus%2Eio%2Fscrape") == "prometheus.io/scrape"

    def test_roundtrip_plain(self):
        assert decode_segment(encode_segment("port")) == "port"

    def test_roundtrip_dotted(self):
        original = "prometheus.io/scrape"
        assert decode_segment(encode_segment(original)) == original

    def test_roundtrip_percent(self):
        assert decode_segment(encode_segment("100%")) == "100%"

    def test_roundtrip_space(self):
        assert decode_segment(encode_segment("hello world")) == "hello world"

    def test_roundtrip_hash(self):
        assert decode_segment(encode_segment("my#key")) == "my#key"


class TestBuildUri:
    def test_nested_path(self):
        assert build_uri("vault", ["server", "service", "port"]) == \
            "helmfacts://vault/server.service#port"

    def test_top_level_key(self):
        assert build_uri("vault", ["replicaCount"]) == \
            "helmfacts://vault/#replicaCount"

    def test_two_segment_path(self):
        assert build_uri("vault", ["global", "enabled"]) == \
            "helmfacts://vault/global#enabled"

    def test_dotted_yaml_key(self):
        uri = build_uri("vault", ["podAnnotations", "prometheus.io/scrape"])
        assert uri == "helmfacts://vault/podAnnotations#prometheus%2Eio%2Fscrape"


class TestGenerateUris:
    def test_all_facts_get_uris(self):
        from idi.generation.helm.walker import walk_values
        facts = walk_values({"a": {"b": 1}, "c": "x"})
        generate_uris(facts, "test")
        for f in facts:
            assert f.uri != ""
            assert f.uri.startswith("helmfacts://test/")

    def test_no_collisions(self):
        facts = walk_values({
            "a": {"b": 1, "c": 2},
            "d": "x",
            "e": {"f": {"g": True}},
        })
        generate_uris(facts, "test")
        uris = [f.uri for f in facts]
        assert len(uris) == len(set(uris)), f"URI collisions: {uris}"
