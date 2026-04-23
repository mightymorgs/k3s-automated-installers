"""Tests for programmatic identifier derivation (Section 02).

Validates that:
1. FK suffixes are learned from spec path parameters, not hardcoded
2. Identifier index uses spec-derived signals, not _ID_FIELD_NAMES
3. _GENERIC_IDENTIFIERS and _NEVER_FK_FIELDS are removed
4. fk_suffixes parameter threads through the pipeline
"""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.canonical_resources import (
    CanonicalResourceMap,
    build_canonical_resource_map,
    learn_fk_suffixes,
)
from idi.generation.dep_adapters.target_inference import (
    _DEFAULT_FK_SUFFIXES,
    _has_fk_suffix,
    _type_factor,
    infer_target,
)
from idi.generation.dep_adapters.verify import (
    _strip_fk_suffix,
    apply_identifier_validation,
    build_identifier_index,
    suppress_fan_out,
)
from idi.generation.dep_adapters.base import Dependency


# ── Hardcoded constant removal verification ────────────────────────────


class TestHardcodedConstantsRemoved:
    """Verify that all four hardcoded constant sets have been eliminated."""

    def test_no_common_fk_suffixes(self):
        """_COMMON_FK_SUFFIXES should be renamed to _DEFAULT_FK_SUFFIXES."""
        import idi.generation.dep_adapters.target_inference as ti
        assert not hasattr(ti, "_COMMON_FK_SUFFIXES")
        assert hasattr(ti, "_DEFAULT_FK_SUFFIXES")

    def test_no_never_fk_fields(self):
        """_NEVER_FK_FIELDS should be completely removed."""
        import idi.generation.dep_adapters.target_inference as ti
        assert not hasattr(ti, "_NEVER_FK_FIELDS")

    def test_no_generic_identifiers(self):
        """_GENERIC_IDENTIFIERS should be completely removed from verify."""
        import idi.generation.dep_adapters.verify as v
        assert not hasattr(v, "_GENERIC_IDENTIFIERS")

    def test_no_id_field_names(self):
        """_ID_FIELD_NAMES should be completely removed from verify."""
        import idi.generation.dep_adapters.verify as v
        assert not hasattr(v, "_ID_FIELD_NAMES")


# ── FK suffix learning ─────────────────────────────────────────────────


class TestLearnFkSuffixes:
    """Test spec-derived FK suffix learning."""

    def test_learns_id_suffix(self):
        """Spec with /users/{user_id} learns _id suffix."""
        spec = {"paths": {
            "/users/{user_id}": {"get": {}},
            "/items/{item_id}": {"get": {}},
        }}
        cmap = build_canonical_resource_map(spec)
        suffixes = learn_fk_suffixes(spec, cmap)
        assert "_id" in suffixes

    def test_learns_uuid_suffix(self):
        """Spec with /resources/{resource_uuid} learns _uuid suffix."""
        spec = {"paths": {
            "/resources/{resource_uuid}": {"get": {}},
            "/items/{item_uuid}": {"get": {}},
        }}
        cmap = build_canonical_resource_map(spec)
        suffixes = learn_fk_suffixes(spec, cmap)
        assert "_uuid" in suffixes

    def test_empty_spec_returns_empty(self):
        spec = {"paths": {}}
        cmap = build_canonical_resource_map(spec)
        assert learn_fk_suffixes(spec, cmap) == ()

    def test_single_param_uses_bare_stem(self):
        """Single short param uses bare stem as suffix."""
        spec = {"paths": {"/items/{id}": {"get": {}}}}
        cmap = build_canonical_resource_map(spec)
        suffixes = learn_fk_suffixes(spec, cmap)
        assert "_id" in suffixes


# ── fk_suffixes threading ──────────────────────────────────────────────


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


class TestFkSuffixesThreading:
    """Test that fk_suffixes parameter threads through all functions."""

    def test_has_fk_suffix_with_custom_suffixes(self):
        """Custom suffix list is used instead of defaults."""
        custom = ("_ref", "_key")
        assert _has_fk_suffix("user_ref", custom) is True
        assert _has_fk_suffix("user_id", custom) is False  # _id not in custom

    def test_has_fk_suffix_with_none_uses_defaults(self):
        """None falls back to _DEFAULT_FK_SUFFIXES."""
        assert _has_fk_suffix("user_id", None) is True

    def test_type_factor_with_custom_suffixes(self):
        """Custom suffixes affect FK suffix detection in type factor."""
        info = {"type": "string"}
        # With custom suffix that matches
        assert _type_factor("user_ref", info, fk_suffixes=("_ref",)) == 0.8
        # Same field with different custom suffix that doesn't match
        assert _type_factor("user_ref", info, fk_suffixes=("_key",)) == 0.5

    def test_strip_fk_suffix_with_custom(self):
        """Custom suffixes used for stripping."""
        assert _strip_fk_suffix("user_ref", fk_suffixes=("_ref",)) == "user"
        assert _strip_fk_suffix("user_id", fk_suffixes=("_ref",)) == "user_id"

    def test_strip_fk_suffix_with_none_uses_defaults(self):
        assert _strip_fk_suffix("user_id") == "user"

    def test_suppress_fan_out_accepts_fk_suffixes(self):
        """suppress_fan_out accepts fk_suffixes parameter."""
        deps = [_dep(f"field{i}", "target") for i in range(3)]
        # Should not raise
        result = suppress_fan_out(deps, fk_suffixes=("_id",))
        assert len(result) == 3

    def test_apply_identifier_validation_accepts_fk_suffixes(self):
        """apply_identifier_validation accepts fk_suffixes parameter."""
        deps = [_dep("user_ref", "users")]
        index = {"users": {"user_ref"}}
        result = apply_identifier_validation(deps, index, fk_suffixes=("_ref",))
        assert result[0].confidence == 0.5  # Unchanged (matched)

    def test_infer_target_with_custom_suffixes(self):
        """infer_target uses custom suffixes for candidate generation."""
        known = {"users"}
        # With custom _ref suffix, user_ref should strip to "user" -> match "users"
        target, conf = infer_target(
            "user_ref", {"type": "string"}, known,
            fk_suffixes=("_ref",),
        )
        assert target == "users"


# ── Spec-derived generic identifiers ───────────────────────────────────


class TestSpecDerivedGenericIdentifiers:
    """Test that generic identifiers are derived from identifier_index."""

    def test_stem_in_two_resources_is_generic(self):
        """A stem appearing in 2+ resources is treated as generic."""
        deps = [_dep("id", "target_resource")]
        index = {
            "target_resource": {"slug"},  # id not in target's identifiers
            "users": {"id"},
            "items": {"id"},
        }
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.5  # Passed as generic

    def test_stem_in_one_resource_not_generic(self):
        """A stem appearing in only 1 resource is NOT generic."""
        deps = [_dep("custom_field", "target")]
        index = {
            "target": {"slug"},
            "other": {"custom_field"},  # Only 1 resource
        }
        result = apply_identifier_validation(deps, index)
        assert result[0].confidence == 0.05  # Penalized

    def test_suffix_stripped_before_counting(self):
        """FK suffixes are stripped before counting stems across resources."""
        deps = [_dep("user_id", "orders")]
        index = {
            "orders": {"order_id"},
            "users": {"user_id"},
            "items": {"item_id"},
        }
        # "user" stem (stripped from "user_id") appears only in users (1 resource)
        # But "user_id" matches "user" stem which should be compared
        # Actually user_id stripped -> "user" which only appears once
        # So it won't be generic -> needs to match target's identifiers
        result = apply_identifier_validation(deps, index)
        # "user" stripped form doesn't match "order" stripped form -> penalized
        assert result[0].confidence == 0.05


def _items_spec(properties: dict) -> dict:
    """Build a minimal spec with GET /items returning given properties."""
    return {
        "paths": {
            "/items": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": properties,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


_ITEMS_SKILL_PATHS = {
    "svc/items/list": {
        "resource": "items", "operation": "list",
        "method": "GET", "endpoint": "/items",
    },
}


class TestBuildIdentifierIndexSpecDerived:
    """Test that build_identifier_index uses spec-derived signals only."""

    def test_integer_fields_detected(self):
        """Integer response fields are detected as identifiers."""
        spec = _items_spec({
            "id": {"type": "integer"},
            "count": {"type": "integer"},
        })
        index = build_identifier_index(spec, _ITEMS_SKILL_PATHS)
        ids = index.get("items", set())
        assert "id" in ids
        assert "count" in ids

    def test_readonly_string_fields_detected(self):
        """readOnly string fields are detected as identifiers."""
        spec = _items_spec({
            "slug": {"type": "string", "readOnly": True},
            "description": {"type": "string"},
        })
        index = build_identifier_index(spec, _ITEMS_SKILL_PATHS)
        ids = index.get("items", set())
        assert "slug" in ids
        assert "description" not in ids

    def test_fk_suffixes_parameter_used(self):
        """Custom fk_suffixes parameter affects suffix detection."""
        spec = _items_spec({
            "item_ref": {"type": "string"},
            "item_id": {"type": "string"},
        })
        # With _ref as suffix, item_ref matches; with default, item_id matches
        index = build_identifier_index(spec, _ITEMS_SKILL_PATHS, fk_suffixes=("_ref",))
        ids = index.get("items", set())
        assert "item_ref" in ids
