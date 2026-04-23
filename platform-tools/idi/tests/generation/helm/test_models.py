"""Tests for helm extractor models, constants, and context."""
from __future__ import annotations

from typing import Any

import pytest

from idi.generation.helm.models import (
    AnnotationInfo,
    Classification,
    HelmEdge,
    HelmFact,
    HelmSignal,
    SchemaInfo,
    VALID_SHAPES,
    VALID_SIGNAL_TYPES,
    VALID_RESOURCE_TYPES,
    validate_fact,
    validate_signal,
)
from idi.generation.helm.constants import (
    CREDENTIAL_LEAF_KEYS,
    EXISTING_BINDING_MAP,
    heuristic_classify_shape,
)
from idi.generation.helm.context import HelmContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fact(**overrides: Any) -> HelmFact:
    """Create a HelmFact with sensible defaults, overridden by kwargs."""
    defaults = dict(
        path="test.key",
        path_segments=["test", "key"],
        uri="helmfacts://test/test#key",
        default_value="",
        type="string",
        semantic_type="string",
        has_template=False,
        default_empty=True,
        default_truncated=False,
        shape="config",
        format=None,
        required=False,
        enum=None,
        description=None,
        is_toggle=False,
        conditional_on=None,
        feature=None,
        cross_app_signal=None,
        classifications=[],
        source="heuristic_default",
        confidence=0.50,
        needs_review=True,
    )
    defaults.update(overrides)
    return HelmFact(**defaults)


def _make_signal(**overrides: Any) -> HelmSignal:
    """Create a HelmSignal with sensible defaults."""
    defaults = dict(
        uri="helmfacts://test/auth#existingSecret",
        path="auth.existingSecret",
        signal_type="secret_binding",
        resource_type="Secret",
        evidence="test evidence",
        method="internal_external_pattern",
        confidence=0.85,
        related_facts=[],
    )
    defaults.update(overrides)
    return HelmSignal(**defaults)


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestClassification:
    def test_stores_all_fields(self):
        c = Classification(
            field="shape",
            value="credential",
            method="schema_format",
            confidence=0.95,
            evidence="schema format=password",
        )
        assert c.field == "shape"
        assert c.value == "credential"
        assert c.method == "schema_format"
        assert c.confidence == 0.95
        assert c.evidence == "schema format=password"

    def test_float_confidence_precision(self):
        c = Classification("shape", "config", "heuristic_default", 0.50, "test")
        assert c.confidence == 0.50
        c2 = Classification("shape", "identity", "kind_registry", 0.90, "test")
        assert c2.confidence == 0.90


# ---------------------------------------------------------------------------
# HelmFact tests
# ---------------------------------------------------------------------------

class TestHelmFact:
    def test_initializes_with_all_fields(self):
        fact = _make_fact()
        assert fact.path == "test.key"
        assert fact.path_segments == ["test", "key"]
        assert fact.uri == "helmfacts://test/test#key"
        assert fact.type == "string"
        assert fact.shape == "config"

    def test_default_truncated_defaults_false(self):
        fact = _make_fact()
        assert fact.default_truncated is False

    def test_needs_review_true_when_low_confidence(self):
        fact = _make_fact(confidence=0.50, needs_review=True)
        assert fact.needs_review is True

    def test_needs_review_false_when_high_confidence(self):
        fact = _make_fact(confidence=0.85, needs_review=False)
        assert fact.needs_review is False


# ---------------------------------------------------------------------------
# HelmEdge tests
# ---------------------------------------------------------------------------

class TestHelmEdge:
    def test_needs_review_true_when_low_confidence(self):
        edge = HelmEdge(
            source="helmfacts://a/b#c",
            target="helmfacts://a/d#e",
            type="DEPENDS_ON",
            method="toggle_hierarchy",
            confidence=0.60,
            evidence="test",
            conditional_value=None,
            needs_review=True,
        )
        assert edge.needs_review is True

    def test_needs_review_false_when_high_confidence(self):
        edge = HelmEdge(
            source="helmfacts://a/b#c",
            target="helmfacts://a/d#e",
            type="DEPENDS_ON",
            method="toggle_hierarchy",
            confidence=0.85,
            evidence="test",
            conditional_value=None,
            needs_review=False,
        )
        assert edge.needs_review is False


# ---------------------------------------------------------------------------
# Vocabulary validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_fact_valid_shapes(self):
        for shape in VALID_SHAPES:
            fact = _make_fact(shape=shape)
            errors = validate_fact(fact)
            assert errors == [], f"Expected no errors for shape={shape}, got {errors}"

    def test_validate_fact_invalid_shape(self):
        fact = _make_fact(shape="unknown_shape")
        errors = validate_fact(fact)
        assert len(errors) == 1
        assert "shape" in errors[0]

    def test_validate_signal_valid_types(self):
        for st in VALID_SIGNAL_TYPES:
            signal = _make_signal(signal_type=st)
            errors = validate_signal(signal)
            assert errors == [], f"Expected no errors for signal_type={st}, got {errors}"

    def test_validate_signal_invalid_type(self):
        signal = _make_signal(signal_type="bad_type")
        errors = validate_signal(signal)
        assert len(errors) == 1
        assert "signal_type" in errors[0]

    def test_validate_signal_invalid_resource_type(self):
        signal = _make_signal(resource_type="BadResource")
        errors = validate_signal(signal)
        assert len(errors) == 1
        assert "resource_type" in errors[0]


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_existing_binding_map_has_expected_entries(self):
        assert "secret" in EXISTING_BINDING_MAP
        assert "claim" in EXISTING_BINDING_MAP
        assert "configmap" in EXISTING_BINDING_MAP
        assert EXISTING_BINDING_MAP["secret"] == ("secret_binding", "Secret")
        assert EXISTING_BINDING_MAP["claim"] == ("pvc_binding", "PersistentVolumeClaim")

    def test_credential_leaf_keys_has_expected_entries(self):
        assert "password" in CREDENTIAL_LEAF_KEYS
        assert "token" in CREDENTIAL_LEAF_KEYS
        assert "secretKey" in CREDENTIAL_LEAF_KEYS
        assert "apiKey" in CREDENTIAL_LEAF_KEYS

    def test_heuristic_secretName_is_identity(self):
        assert heuristic_classify_shape("secretName", "") == "identity"

    def test_heuristic_host_is_addressability(self):
        assert heuristic_classify_shape("host", "") == "addressability"

    def test_heuristic_password_is_credential(self):
        assert heuristic_classify_shape("password", "") == "credential"

    def test_heuristic_replicaCount_is_config(self):
        assert heuristic_classify_shape("replicaCount", 3) == "config"

    def test_heuristic_apiKey_is_credential_not_identity(self):
        # "apiKey" ends in "Key" (identity suffix) but "apikey" substring
        # matches credential keywords. Credential should win.
        assert heuristic_classify_shape("apiKey", "") == "credential"


# ---------------------------------------------------------------------------
# HelmContext tests
# ---------------------------------------------------------------------------

class TestHelmContext:
    def test_context_default_factories(self):
        ctx = HelmContext(
            chart_name="test",
            chart_version="1.0.0",
            app_version="1.0.0",
            repository="https://example.com",
            values={},
            chart_meta={},
            values_text="",
            kind_registry=None,  # type: ignore
        )
        assert ctx.facts == []
        assert ctx.edges == []
        assert ctx.signals == []
        assert ctx.library_deps == []
        assert ctx.subchart_deps == []
        assert ctx.schema_overrides == {}
        assert ctx.annotations == {}
        assert ctx.chart_conditions == {}
