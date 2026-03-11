"""Tests for generic response envelope detection.

Tests the 4 envelope patterns: HAL _embedded, pagination, single-field wrapper,
and externally tagged. Each pattern has positive and negative test cases.
Confidence threshold behavior (>= 0.8 to act) is verified.
"""
from __future__ import annotations

import pytest

from idi.generation.adapters.envelope_detector import (
    detect_envelope,
    navigate_unwrap_path,
    EnvelopeResult,
)


# ---------------------------------------------------------------------------
# HAL _embedded pattern
# ---------------------------------------------------------------------------

class TestHalEmbedded:

    def test_hal_embedded_single_resource(self):
        """Response with _embedded.users array unwraps to '_embedded.users' at 0.95."""
        schema = {
            "type": "object",
            "properties": {
                "_embedded": {
                    "type": "object",
                    "properties": {
                        "users": {
                            "type": "array",
                            "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                        },
                    },
                },
                "_links": {"type": "object"},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.unwrap_path == "_embedded.users"
        assert result.pattern == "hal_embedded"
        assert result.confidence == 0.95

    def test_hal_embedded_no_sub_properties(self):
        """_embedded without sub-properties -> no match."""
        schema = {
            "type": "object",
            "properties": {
                "_embedded": {"type": "object"},
            },
        }
        result = detect_envelope(schema)
        # Should not match HAL pattern (no sub-properties)
        assert result is None or result.pattern != "hal_embedded"


# ---------------------------------------------------------------------------
# Pagination wrapper pattern
# ---------------------------------------------------------------------------

class TestPagination:

    def test_pagination_items_with_metadata(self):
        """Standard pagination with items array + total/page metadata."""
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
                "total": {"type": "integer"},
                "page": {"type": "integer"},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.unwrap_path == "items"
        assert result.pattern == "pagination"
        assert result.confidence == 0.9

    def test_pagination_multiple_arrays(self):
        """Multiple arrays present; only the data-named array is selected."""
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
                "errors": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "total": {"type": "integer"},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.unwrap_path == "items"

    def test_pagination_first_data_match(self):
        """When multiple data-named arrays exist, first match wins."""
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
                "results": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "count": {"type": "integer"},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.unwrap_path == "data"


# ---------------------------------------------------------------------------
# Single-field wrapper pattern
# ---------------------------------------------------------------------------

class TestSingleFieldWrapper:

    def test_single_field_with_metadata_sibling(self):
        """Single data field with metadata sibling gets 0.9 confidence."""
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                },
                "errors": {"type": "array", "items": {"type": "object"}},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.unwrap_path == "data"
        assert result.pattern == "single_field"
        assert result.confidence == 0.9

    def test_single_field_without_metadata_sibling(self):
        """Single data field without metadata gets 0.7 — below action threshold."""
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
                "timestamp": {"type": "string", "format": "date-time"},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.pattern == "single_field"
        assert result.confidence == 0.7

    def test_single_field_primitive_array_not_unwrapped(self):
        """Primitive arrays are never envelopes. Type guard prevents unwrapping."""
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
        }
        result = detect_envelope(schema)
        # Should not match single_field for primitive arrays
        assert result is None or result.pattern != "single_field"

    def test_single_field_primitive_not_unwrapped(self):
        """Primitive values are never envelopes. Type guard prevents unwrapping."""
        schema = {
            "type": "object",
            "properties": {
                "data": {"type": "string"},
            },
        }
        result = detect_envelope(schema)
        assert result is None or result.pattern != "single_field"


# ---------------------------------------------------------------------------
# Externally tagged pattern
# ---------------------------------------------------------------------------

class TestExternallyTagged:

    def test_externally_tagged_matches_path(self):
        """Property name matching last path segment unwraps at 0.95."""
        schema = {
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            },
        }
        result = detect_envelope(schema, path="/users")
        assert result is not None
        assert result.unwrap_path == "users"
        assert result.pattern == "externally_tagged"
        assert result.confidence == 0.95

    def test_externally_tagged_no_match_without_path(self):
        """Without path param, externally tagged can't match."""
        schema = {
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            },
        }
        result = detect_envelope(schema, path=None)
        # Without a path, externally_tagged can't match
        assert result is None or result.pattern != "externally_tagged"

    def test_externally_tagged_case_insensitive(self):
        """Case-insensitive match between path segment and property name."""
        schema = {
            "type": "object",
            "properties": {
                "Users": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            },
        }
        result = detect_envelope(schema, path="/users")
        assert result is not None
        assert result.pattern == "externally_tagged"


# ---------------------------------------------------------------------------
# Negative / threshold tests
# ---------------------------------------------------------------------------

class TestNegativeAndThreshold:

    def test_no_pattern_matched(self):
        """Schema with no envelope characteristics returns None."""
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        result = detect_envelope(schema)
        assert result is None

    def test_below_threshold_not_acted_on(self):
        """Results below 0.8 confidence are returned but caller must not unwrap."""
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
                "timestamp": {"type": "string"},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.confidence == 0.7  # Below 0.8 threshold

    def test_above_threshold_acted_on(self):
        """Results at or above 0.8 confidence are valid for unwrapping."""
        schema = {
            "type": "object",
            "properties": {
                "result": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
                },
                "success": {"type": "boolean"},
                "errors": {"type": "array", "items": {"type": "object"}},
            },
        }
        result = detect_envelope(schema)
        assert result is not None
        assert result.confidence >= 0.8

    def test_empty_schema(self):
        """Empty schema returns None."""
        assert detect_envelope({}) is None
        assert detect_envelope({"type": "object"}) is None

    def test_non_object_schema(self):
        """Non-object schema returns None."""
        schema = {"type": "array", "items": {"type": "string"}}
        assert detect_envelope(schema) is None


# ---------------------------------------------------------------------------
# navigate_unwrap_path tests
# ---------------------------------------------------------------------------

class TestNavigateUnwrapPath:

    def test_single_segment(self):
        """Navigate one level: 'data' -> properties.data."""
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            },
        }
        result = navigate_unwrap_path(schema, "data")
        assert result is not None
        assert result["type"] == "object"
        assert "id" in result["properties"]

    def test_two_segments(self):
        """Navigate two levels: '_embedded.users'."""
        schema = {
            "type": "object",
            "properties": {
                "_embedded": {
                    "type": "object",
                    "properties": {
                        "users": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                },
            },
        }
        result = navigate_unwrap_path(schema, "_embedded.users")
        assert result is not None
        assert result["type"] == "array"

    def test_missing_segment_returns_none(self):
        """Navigate to non-existent property returns None."""
        schema = {"type": "object", "properties": {"data": {"type": "object"}}}
        assert navigate_unwrap_path(schema, "missing") is None

    def test_no_properties_returns_none(self):
        """Schema without properties returns None."""
        assert navigate_unwrap_path({"type": "object"}, "data") is None
        assert navigate_unwrap_path({}, "data") is None
