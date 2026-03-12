"""Tests for target_inference.py — schema gates (s03) + suffix hardening (s09)."""
import pytest

from idi.generation.dep_adapters.target_inference import _match_resource, _type_factor


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


class TestSuffixContainmentHardening:
    """Suffix containment minimum token length raised from 4 to 7 (section-09)."""

    # Resources used as the known-set for suffix matching.
    _RESOURCES = frozenset({
        "qualityprofile",          # suffix match for "profile" (7 chars)
        "auth-provider",           # suffix match for "provider" (8 chars)
        "sysmfamethod",            # would false-match "method" (6 chars)
        "managed-resources",       # would false-match "source" (6 chars)
        "roles-composites-realm",  # would false-match "realm" (5 chars)
        "some-type-resource",      # would false-match "type" (4 chars)
    })

    def test_4char_type_does_not_suffix_match(self):
        """'type' (4 chars) must NOT match via suffix containment."""
        result = _match_resource("type", self._RESOURCES)
        assert result is None

    def test_5char_realm_does_not_suffix_match(self):
        """'realm' (5 chars) must NOT match via suffix containment."""
        result = _match_resource("realm", self._RESOURCES)
        assert result is None

    def test_6char_method_does_not_suffix_match(self):
        """'method' (6 chars) must NOT match via suffix containment."""
        result = _match_resource("method", self._RESOURCES)
        assert result is None

    def test_6char_source_does_not_suffix_match(self):
        """'source' (6 chars) must NOT match 'managed-resources' via suffix."""
        result = _match_resource("source", self._RESOURCES)
        assert result is None

    def test_7char_profile_does_suffix_match(self):
        """'profile' (7 chars) DOES match 'qualityprofile' via suffix."""
        result = _match_resource("profile", self._RESOURCES)
        assert result is not None
        name, confidence = result
        assert name == "qualityprofile"
        assert confidence == 0.2

    def test_8char_provider_does_suffix_match(self):
        """'provider' (8 chars) DOES match 'auth-provider' via suffix."""
        result = _match_resource("provider", self._RESOURCES)
        assert result is not None
        name, confidence = result
        assert name == "auth-provider"
        assert confidence == 0.2

    def test_short_candidates_still_match_via_other_strategies(self):
        """Candidates below suffix threshold can still match exactly."""
        resources = frozenset({"type", "realm", "method"})
        # Exact match still works for short candidates
        for candidate in ("type", "realm", "method"):
            result = _match_resource(candidate, resources)
            assert result is not None, f"'{candidate}' should exact-match"
            assert result[0] == candidate
