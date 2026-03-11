"""Tests for _type_factor schema gates in target_inference.py (section-03)."""
import pytest

from idi.generation.dep_adapters.target_inference import _type_factor


class TestTypeFactorSchemaGates:
    """Schema signal gates — enum, readOnly, non-FK formats, pattern."""

    # --- Enum gate ---
    def test_enum_string_returns_zero(self):
        info = {"type": "string", "enum": ["read", "write"]}
        assert _type_factor("permission", info) == 0.0

    def test_enum_integer_returns_zero(self):
        info = {"type": "integer", "enum": [1, 2, 3]}
        assert _type_factor("status", info) == 0.0

    def test_enum_fires_before_type_branching_integer(self):
        """Integer+enum should be 0.0 (enum gate), not 1.0 (integer branch)."""
        info = {"type": "integer", "enum": [0, 1, 2]}
        assert _type_factor("priority", info) == 0.0

    def test_empty_enum_does_not_trigger_gate(self):
        """Empty enum list is falsy — should pass through to type branching."""
        info = {"type": "integer", "enum": []}
        assert _type_factor("project_id", info) == 1.0

    # --- readOnly gate ---
    def test_readonly_returns_zero(self):
        info = {"type": "string", "readOnly": True}
        assert _type_factor("user_id", info) == 0.0

    def test_readonly_fires_before_type_branching(self):
        """readOnly integer should be 0.0, not 1.0."""
        info = {"type": "integer", "readOnly": True}
        assert _type_factor("count", info) == 0.0

    def test_readonly_false_does_not_trigger_gate(self):
        """Explicit readOnly: false should not block the field."""
        info = {"type": "integer", "readOnly": False}
        assert _type_factor("project_id", info) == 1.0

    # --- Non-FK format gate ---
    @pytest.mark.parametrize("fmt", [
        "date-time", "email", "uri", "ipv4", "duration", "hostname", "password",
    ])
    def test_non_fk_format_returns_zero(self, fmt):
        info = {"type": "string", "format": fmt}
        assert _type_factor("some_field", info) == 0.0

    def test_uuid_format_still_returns_one(self):
        """uuid format is a strong FK signal — must NOT be blocked."""
        info = {"type": "string", "format": "uuid"}
        # uuid is handled as format=="uuid" → 1.0 in the integer/uuid branch
        assert _type_factor("some_field", info) == 1.0

    # --- Pattern constraint ---
    def test_pattern_string_returns_low(self):
        info = {"type": "string", "pattern": r"^[A-Z]{3}$"}
        assert _type_factor("code", info) == 0.1

    # --- Baseline: existing behavior preserved ---
    def test_integer_without_enum_still_returns_one(self):
        info = {"type": "integer"}
        assert _type_factor("project_id", info) == 1.0

    def test_string_with_fk_suffix_still_returns_high(self):
        info = {"type": "string"}
        assert _type_factor("project_id", info) == 0.8

    def test_plain_string_still_returns_half(self):
        info = {"type": "string"}
        assert _type_factor("project", info) == 0.5

    def test_never_fk_field_still_returns_zero(self):
        info = {"type": "string"}
        assert _type_factor("description", info) == 0.0
