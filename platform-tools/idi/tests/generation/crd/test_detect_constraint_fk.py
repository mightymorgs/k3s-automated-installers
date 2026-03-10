"""Tests for detect_constraint_fk (C29) in ref_detector.py."""
from __future__ import annotations

import pytest

from idi.generation.crd.kind_registry import KindRegistry
from idi.generation.crd.ref_detector import (
    K8S_NAME_PATTERNS,
    _is_k8s_name_pattern,
    detect_constraint_fk,
)
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> KindRegistry:
    return KindRegistry()


def _make_field(
    name: str,
    schema: dict | None = None,
    path: str | None = None,
    parent_path: str = "spec",
) -> WalkedField:
    if schema is None:
        schema = {"type": "string"}
    if path is None:
        path = f"{parent_path}.{name}"
    return WalkedField(
        path=path,
        name=name,
        schema=schema,
        depth=1,
        is_array_item=False,
        required=False,
        parent_path=parent_path,
    )


# ---------------------------------------------------------------------------
# Tests: _is_k8s_name_pattern
# ---------------------------------------------------------------------------


class TestIsK8sNamePattern:
    def test_matches_rfc1123(self):
        assert _is_k8s_name_pattern(K8S_NAME_PATTERNS[0]) is True

    def test_rejects_unrelated(self):
        assert _is_k8s_name_pattern(r"^\d{4}-\d{2}-\d{2}$") is False

    def test_matches_all_known_patterns(self):
        for pat in K8S_NAME_PATTERNS:
            assert _is_k8s_name_pattern(pat) is True


# ---------------------------------------------------------------------------
# Tests: detect_constraint_fk
# ---------------------------------------------------------------------------


class TestDetectConstraintFk:
    def test_dns_pattern_with_namespace_sibling(self, registry):
        """String field with DNS pattern + namespace sibling -> input_ref at 0.75."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "server": {"type": "string", "pattern": K8S_NAME_PATTERNS[0]},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is not None
        assert result.role == "input_ref"
        assert result.confidence == 0.75
        assert result.detection_source == "ref_detector:constraint_fk"

    def test_dns_pattern_namespace_and_kind_sibling(self, registry):
        """DNS pattern + namespace + kind sibling -> confidence 0.80."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "server": {"type": "string"},
            "namespace": {"type": "string"},
            "kind": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is not None
        assert result.confidence == 0.80

    def test_dns_pattern_no_namespace(self, registry):
        """DNS pattern but no namespace sibling -> None."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "server": {"type": "string"},
            "config": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_no_pattern_no_format(self, registry):
        """String field without pattern or format -> None."""
        field = _make_field("server", schema={"type": "string"})
        parent_properties = {
            "server": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_length_only_rejected(self, registry):
        """maxLength/minLength alone -> None (length-only removed)."""
        field = _make_field("server", schema={
            "type": "string",
            "maxLength": 253,
            "minLength": 1,
        })
        parent_properties = {
            "server": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_format_dns1123_label(self, registry):
        """format=dns1123-label + namespace -> input_ref at 0.75."""
        field = _make_field("target", schema={
            "type": "string",
            "format": "dns1123-label",
        })
        parent_properties = {
            "target": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is not None
        assert result.confidence == 0.75

    def test_format_hostname(self, registry):
        """format=hostname + namespace -> input_ref."""
        field = _make_field("host", schema={
            "type": "string",
            "format": "hostname",
        })
        parent_properties = {
            "host": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is not None

    def test_format_email_rejected(self, registry):
        """format=email (not in allowlist) -> None."""
        field = _make_field("contact", schema={
            "type": "string",
            "format": "email",
        })
        parent_properties = {
            "contact": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_self_exclusion_namespace(self, registry):
        """Field named 'namespace' -> None (self-exclusion)."""
        field = _make_field("namespace", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "namespace": {"type": "string"},
            "name": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_self_exclusion_case_insensitive(self, registry):
        """Field named 'Namespace' -> None."""
        field = _make_field("Namespace", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "Namespace": {"type": "string"},
            "name": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_non_string_type(self, registry):
        """Non-string field -> None."""
        field = _make_field("count", schema={"type": "integer"})
        parent_properties = {
            "count": {"type": "integer"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_namespace_sibling_not_string(self, registry):
        """Namespace sibling is integer -> None."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "server": {"type": "string"},
            "namespace": {"type": "integer"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_target_namespace_not_exact_match(self, registry):
        """Sibling named 'targetNamespace' -> not a match (exact match required)."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "server": {"type": "string"},
            "targetNamespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is None

    def test_no_parent_properties(self, registry):
        """No parent_properties passed -> None (cannot check siblings)."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        result = detect_constraint_fk(field, registry, parent_properties=None)
        assert result is None

    def test_target_kind_is_none(self, registry):
        """Constraint FK cannot resolve target Kind -> target_kind is None."""
        field = _make_field("server", schema={
            "type": "string",
            "pattern": K8S_NAME_PATTERNS[0],
        })
        parent_properties = {
            "server": {"type": "string"},
            "namespace": {"type": "string"},
        }
        result = detect_constraint_fk(field, registry, parent_properties=parent_properties)
        assert result is not None
        assert result.target_kind is None
