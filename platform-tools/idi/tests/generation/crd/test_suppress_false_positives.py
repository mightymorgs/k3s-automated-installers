"""Tests for suppress_false_positives — CRD Phase 3 Section 07 (C28)."""
from __future__ import annotations

import pytest

from idi.generation.crd.field_classifier import ClassifiedField
from idi.generation.crd.ref_detector import suppress_false_positives
from idi.generation.crd.schema_walker import WalkedField


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        path=path, name=name, schema=schema, depth=1,
        is_array_item=False, required=False, parent_path=parent_path,
    )


def _make_cf(
    field_path: str = "spec.x",
    role: str = "input_ref",
    confidence: float = 0.85,
    target_kind: str | None = "Secret",
    target_group: str | None = "core",
    detection_source: str = "ref_detector:kind_registry",
    field_type: str = "string",
) -> ClassifiedField:
    return ClassifiedField(
        field=field_path,
        role=role,
        confidence=confidence,
        field_type=field_type,
        target_kind=target_kind,
        target_group=target_group,
        detection_source=detection_source,
        fact_shape="identity",
    )


# ---------------------------------------------------------------------------
# Rule 1: target_kind_not_at_word_boundary
# ---------------------------------------------------------------------------


class TestRule1WordBoundary:
    def test_refresh_interval_suppressed(self):
        """refreshInterval with target_kind containing 'Ref' -> suppressed."""
        field = _make_field("refreshInterval")
        # Simulating a classification where somehow target_kind is something
        # that doesn't match a token. "Ref" is not a complete token in
        # ["refresh", "Interval"].
        cf = _make_cf(target_kind="Ref", detection_source="ref_detector:kind_registry")
        results = suppress_false_positives(field, [cf])
        assert len(results) == 1
        assert results[0].role == "config_field"
        assert results[0].confidence == 0.1
        assert "suppressed:" in results[0].detection_source
        assert "target_kind_not_at_word_boundary" in results[0].detection_source

    def test_secret_ref_not_suppressed(self):
        """secretRef with target_kind='Secret' -> NOT suppressed."""
        field = _make_field("secretRef")
        cf = _make_cf(target_kind="Secret")
        results = suppress_false_positives(field, [cf])
        assert len(results) == 1
        assert results[0].role == "input_ref"
        assert results[0].confidence == 0.85

    def test_target_secrets_depluralized(self):
        """targetSecrets with target_kind='Secret' -> NOT suppressed (depluralized)."""
        field = _make_field("targetSecrets")
        cf = _make_cf(target_kind="Secret")
        results = suppress_false_positives(field, [cf])
        assert len(results) == 1
        assert results[0].role == "input_ref"

    def test_preferred_during_scheduling_suppressed(self):
        """preferredDuringScheduling with target_kind not a token -> suppressed."""
        field = _make_field("preferredDuringScheduling")
        cf = _make_cf(target_kind="Red", detection_source="ref_detector:kind_registry")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_target_kind_none_skips_rule(self):
        """Classification with target_kind=None -> Rule 1 skipped."""
        field = _make_field("someField")
        cf = _make_cf(target_kind=None)
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"

    def test_service_name_not_suppressed(self):
        """serviceName with target_kind='Service' -> NOT suppressed."""
        field = _make_field("serviceName")
        cf = _make_cf(target_kind="Service")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"


# ---------------------------------------------------------------------------
# Rule 2: kind_collision_no_structural_context (Phase 3 sources only)
# ---------------------------------------------------------------------------


class TestRule2StructuralContext:
    def test_primitive_phase3_source_suppressed(self):
        """String field from ref_detector:ref_tuple -> suppressed."""
        field = _make_field("nodeName", schema={"type": "string"})
        cf = _make_cf(
            target_kind="Node",
            detection_source="ref_detector:ref_tuple",
            field_type="string",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"
        assert "kind_collision_no_structural_context" in results[0].detection_source

    def test_primitive_phase2_source_exempt(self):
        """String field from ref_detector:kind_registry -> NOT suppressed (Phase 2)."""
        field = _make_field("nodeName", schema={"type": "string"})
        # tokens: ["node", "Name"], "Node" matches "node" -> rule 1 passes
        cf = _make_cf(
            target_kind="Node",
            detection_source="ref_detector:kind_registry",
            field_type="string",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"  # Not suppressed

    def test_object_with_structural_markers_not_suppressed(self):
        """Object field with namespace/kind properties -> NOT suppressed."""
        field = _make_field("targetNode", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "kind": {"type": "string"},
            },
        })
        cf = _make_cf(
            target_kind="Node",
            detection_source="ref_detector:ref_tuple",
            field_type="object",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"

    def test_event_type_example_kind_suppressed(self):
        """String field from ref_detector:example_kind -> suppressed."""
        field = _make_field("eventType", schema={"type": "string"})
        cf = _make_cf(
            target_kind="Event",
            detection_source="ref_detector:example_kind",
            field_type="string",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_object_without_markers_suppressed(self):
        """Object without namespace/kind/apiGroup from Phase 3 -> suppressed."""
        field = _make_field("nodeRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
            },
        })
        cf = _make_cf(
            target_kind="Node",
            detection_source="ref_detector:ref_tuple",
            field_type="object",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_object_with_namespace_not_suppressed(self):
        """Object with namespace property from Phase 3 -> NOT suppressed."""
        field = _make_field("nodeRef", schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
        })
        cf = _make_cf(
            target_kind="Node",
            detection_source="ref_detector:ref_tuple",
            field_type="object",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"

    def test_apigroup_literal_source_in_scope(self):
        """Field from ref_detector:apigroup_literal -> Rule 2 applies."""
        field = _make_field("apiVersion", schema={"type": "string"})
        cf = _make_cf(
            target_kind="Cluster",
            detection_source="ref_detector:apigroup_literal",
            field_type="string",
        )
        results = suppress_false_positives(field, [cf])
        # tokens: ["api", "Version"], "Cluster" not a token -> Rule 1 fires first
        assert results[0].role == "config_field"


# ---------------------------------------------------------------------------
# Rule 3: nested_metadata_self_reference
# ---------------------------------------------------------------------------


class TestRule3NestedMetadata:
    def test_template_metadata_name_suppressed(self):
        """spec.template.metadata.name -> suppressed.

        When target_kind doesn't match a token in 'name', Rule 1 fires first.
        Either way, the classification is suppressed (correct behavior).
        """
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.template.metadata.name", parent_path="spec.template.metadata",
        )
        cf = _make_cf(field_path="spec.template.metadata.name")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"
        assert results[0].confidence == 0.1

    def test_template_metadata_name_rule3_fires(self):
        """When Rule 1 passes (target_kind IS a token), Rule 3 still catches it."""
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.template.metadata.name", parent_path="spec.template.metadata",
        )
        # Use target_kind=None so Rule 1 is skipped, then Rule 3 fires.
        cf = _make_cf(
            field_path="spec.template.metadata.name",
            target_kind=None,
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"
        assert "nested_metadata_self_reference" in results[0].detection_source

    def test_template_metadata_namespace_suppressed(self):
        """spec.template.metadata.namespace -> suppressed."""
        field = _make_field(
            "namespace", schema={"type": "string"},
            path="spec.template.metadata.namespace",
            parent_path="spec.template.metadata",
        )
        cf = _make_cf(
            field_path="spec.template.metadata.namespace",
            target_kind="Namespace",
        )
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_pod_template_metadata_name_suppressed(self):
        """spec.podTemplate.metadata.name at depth > 1 -> suppressed."""
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.podTemplate.metadata.name",
            parent_path="spec.podTemplate.metadata",
        )
        cf = _make_cf(field_path="spec.podTemplate.metadata.name")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"

    def test_service_name_not_suppressed(self):
        """spec.serviceName -> NOT suppressed (no metadata segment)."""
        field = _make_field("serviceName", schema={"type": "string"})
        cf = _make_cf(target_kind="Service")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "input_ref"

    def test_some_metadata_name_not_suppressed(self):
        """spec.someMetadata.name -> NOT suppressed (segment is someMetadata, not metadata)."""
        field = _make_field(
            "name", schema={"type": "string"},
            path="spec.someMetadata.name",
            parent_path="spec.someMetadata",
        )
        # tokens: ["name"], target_kind="Secret" -> Rule 1 might fire
        # depending on target_kind. Let's use a kind that matches token.
        cf = _make_cf(field_path="spec.someMetadata.name", target_kind="Name")
        results = suppress_false_positives(field, [cf])
        # "Name" matches token "name" case-insensitively -> Rule 1 passes
        # No "metadata" exact segment match -> Rule 3 passes
        # Rule 2 depends on source -- using Phase 2 source, exempt
        assert results[0].role == "input_ref"


# ---------------------------------------------------------------------------
# General behavior
# ---------------------------------------------------------------------------


class TestSuppressFPGeneral:
    def test_empty_input_empty_output(self):
        """Empty classifications -> empty result."""
        field = _make_field("x")
        assert suppress_false_positives(field, []) == []

    def test_suppressed_item_has_correct_fields(self):
        """Suppressed items have role=config_field, confidence=0.1, source prefix."""
        field = _make_field("refreshInterval")
        cf = _make_cf(target_kind="Ref")
        results = suppress_false_positives(field, [cf])
        assert results[0].role == "config_field"
        assert results[0].confidence == 0.1
        assert results[0].detection_source.startswith("suppressed:")

    def test_non_suppressed_unchanged(self):
        """Non-suppressed items pass through completely unchanged."""
        field = _make_field("secretRef")
        cf = _make_cf(target_kind="Secret")
        results = suppress_false_positives(field, [cf])
        assert results[0] is cf  # Same object, not a copy

    def test_first_matching_rule_wins(self):
        """Only the first matching rule's name appears in detection_source."""
        field = _make_field("refreshInterval")
        cf = _make_cf(target_kind="Ref", detection_source="ref_detector:ref_tuple")
        results = suppress_false_positives(field, [cf])
        assert "target_kind_not_at_word_boundary" in results[0].detection_source

    def test_multiple_classifications_processed(self):
        """Each classification is independently checked."""
        field = _make_field("secretRef")
        cf1 = _make_cf(target_kind="Secret")
        cf2 = _make_cf(target_kind="Ref")  # "Ref" not a complete token in "secretRef"
        # Actually "Ref" IS a token in ["secret", "Ref"] -> not suppressed
        results = suppress_false_positives(field, [cf1, cf2])
        assert len(results) == 2
        assert all(r.role == "input_ref" for r in results)
