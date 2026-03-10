"""Tests for decomposed CRD output writer — CRD Phase 1b."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.crd.field_classifier import ClassifiedField, classify_fields
from idi.generation.crd.output_writer import (
    _compute_content_hash,
    _resolve_filenames,
    _sanitize_path_segment,
    _satisfaction_for_field,
    build_decomposed_skill,
    write_decomposed_skill,
)
from tests.generation.crd.conftest import _FIXTURES_DIR


def _load_fixture(service: str, kind: str) -> dict[str, Any]:
    path = _FIXTURES_DIR / service / f"{kind}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _classify_fixture(fixture: dict[str, Any], registry) -> list[ClassifiedField]:
    return classify_fields(
        spec_properties=fixture["spec_properties"],
        spec_required=fixture["spec_required"],
        group=fixture["group"],
        kind=fixture["kind"],
        registry=registry,
    )


# ---------------------------------------------------------------------------
# Decomposed structure tests
# ---------------------------------------------------------------------------


class TestDecomposedStructure:
    @pytest.fixture(autouse=True)
    def setup(self, populated_registry):
        self.registry = populated_registry
        self.fixture = _load_fixture("cert-manager", "Certificate")
        self.fields = _classify_fixture(self.fixture, self.registry)
        self.skill = build_decomposed_skill(self.fixture, self.fields)

    def test_top_level_keys(self):
        assert set(self.skill.keys()) == {"manifest", "operation", "refs", "outputs", "fields"}

    def test_manifest_schema_version(self):
        assert self.skill["manifest"]["schema_version"] == "2.0"

    def test_manifest_metadata(self):
        m = self.skill["manifest"]
        assert m["kind"] == "Certificate"
        assert m["group"] == "cert-manager.io"
        assert m["version"] == "v1"
        assert m["plural"] == "certificates"
        assert m["scope"] == "namespaced"
        assert m["service"] == "cert-manager"

    def test_manifest_refs_list(self):
        m = self.skill["manifest"]
        assert m["refs"] == sorted(self.skill["refs"].keys())

    def test_manifest_outputs_list(self):
        m = self.skill["manifest"]
        assert m["outputs"] == sorted(self.skill["outputs"].keys())

    def test_manifest_fields_list(self):
        m = self.skill["manifest"]
        assert m["fields"] == sorted(self.skill["fields"].keys())

    def test_operation_action_id(self):
        assert self.skill["operation"]["action_id"] == "configure.cert-manager.certificate"

    def test_operation_depends_on(self):
        depends = self.skill["operation"]["depends_on"]
        # Phase 2 finds more refs via depth traversal; verify issuerRef is present.
        assert len(depends) >= 1
        ref_names = {d["ref"] for d in depends}
        assert "issuerRef" in ref_names

    def test_operation_outputs(self):
        outputs = self.skill["operation"]["outputs"]
        assert len(outputs) >= 1
        output_names = {o["output"] for o in outputs}
        assert "secretName" in output_names


# ---------------------------------------------------------------------------
# Ref content tests
# ---------------------------------------------------------------------------


class TestRefContent:
    @pytest.fixture(autouse=True)
    def setup(self, populated_registry):
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        skill = build_decomposed_skill(fixture, fields)
        self.ref = skill["refs"]["issuerRef"]

    def test_name(self):
        assert self.ref["name"] == "issuerRef"

    def test_field_path(self):
        assert self.ref["field_path"] == "spec.issuerRef"

    def test_target_kind(self):
        assert self.ref["target_kind"] == "Issuer"

    def test_target_group(self):
        assert self.ref["target_group"] == "cert-manager.io"

    def test_fact_ref(self):
        assert self.ref["fact_ref"] == "crdfacts://cert-manager.io/Issuer#name"

    def test_fact_shape(self):
        assert self.ref["fact_shape"] == "identity"

    def test_satisfaction(self):
        assert self.ref["satisfaction"] == "required_value"

    def test_detection_source(self):
        assert self.ref["detection_source"]  # non-empty

    def test_confidence(self):
        assert self.ref["confidence"] == 0.9


# ---------------------------------------------------------------------------
# Output content tests
# ---------------------------------------------------------------------------


class TestOutputContent:
    @pytest.fixture(autouse=True)
    def setup(self, populated_registry):
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        skill = build_decomposed_skill(fixture, fields)
        self.output = skill["outputs"]["secretName"]

    def test_produces_kind(self):
        assert self.output["produces_kind"] == "Secret"

    def test_produces_group(self):
        assert self.output["produces_group"] == "core"

    def test_fact_ref(self):
        assert self.output["fact_ref"] == "crdfacts://core/Secret#name"

    def test_fact_shape(self):
        assert self.output["fact_shape"] == "identity"


# ---------------------------------------------------------------------------
# Field content tests
# ---------------------------------------------------------------------------


class TestFieldContent:
    @pytest.fixture(autouse=True)
    def setup(self, populated_registry):
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        skill = build_decomposed_skill(fixture, fields)
        self.field_common = skill["fields"]["commonName"]
        self.fields = skill["fields"]

    def test_type(self):
        assert self.field_common["type"] == "string"

    def test_fact_shape(self):
        assert self.field_common["fact_shape"] == "config"

    def test_cardinality_one(self):
        assert self.field_common["cardinality"] == "one"

    def test_cardinality_many(self):
        """Array fields have cardinality "many"."""
        dns_field = self.fields.get("dnsNames")
        if dns_field:
            assert dns_field["cardinality"] == "many"


# ---------------------------------------------------------------------------
# Content hash tests
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self, populated_registry):
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        skill1 = build_decomposed_skill(fixture, fields)
        skill2 = build_decomposed_skill(fixture, fields)
        assert skill1["manifest"]["content_hash"] == skill2["manifest"]["content_hash"]

    def test_changes_with_field_modification(self, populated_registry):
        """Content hash changes when classified fields change."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        skill1 = build_decomposed_skill(fixture, fields)

        # Modify a field's description (which IS included in field files).
        import copy
        fields2 = copy.deepcopy(fields)
        for f in fields2:
            if f.field == "spec.commonName":
                f.description = "MODIFIED DESCRIPTION"
        skill2 = build_decomposed_skill(fixture, fields2)
        assert skill1["manifest"]["content_hash"] != skill2["manifest"]["content_hash"]

    def test_canonical_json(self):
        """Content hash uses canonical JSON (sorted keys, no whitespace)."""
        files = {
            "a.json": {"b": 2, "a": 1},
            "b.json": {"x": 1},
        }
        h1 = _compute_content_hash(files)
        # Same data, different insertion order.
        files2 = {
            "b.json": {"x": 1},
            "a.json": {"a": 1, "b": 2},
        }
        h2 = _compute_content_hash(files2)
        assert h1 == h2


# ---------------------------------------------------------------------------
# Collision detection tests
# ---------------------------------------------------------------------------


class TestCollisionDetection:
    def test_hyphen_joined_on_collision(self):
        """Two fields with same leaf name use hyphen-joined paths."""
        fields = [
            ClassifiedField(field="spec.tls.secretRef", role="input_ref", confidence=0.9,
                          field_type="object", target_kind="Secret", target_group="core"),
            ClassifiedField(field="spec.auth.secretRef", role="input_ref", confidence=0.9,
                          field_type="object", target_kind="Secret", target_group="core"),
        ]
        result = _resolve_filenames(fields, "input_ref")
        assert result["spec.tls.secretRef"] == "tls-secretRef"
        assert result["spec.auth.secretRef"] == "auth-secretRef"

    def test_case_insensitive_collision(self):
        """Case-insensitive collision detection."""
        fields = [
            ClassifiedField(field="spec.issuerRef", role="input_ref", confidence=0.9,
                          field_type="object", target_kind="Issuer"),
            ClassifiedField(field="spec.alt.IssuerRef", role="input_ref", confidence=0.9,
                          field_type="object", target_kind="Issuer"),
        ]
        result = _resolve_filenames(fields, "input_ref")
        # Both should use hyphen-joined form.
        assert result["spec.issuerRef"] == "issuerRef"  # No spec. prefix -> just leaf
        assert result["spec.alt.IssuerRef"] == "alt-IssuerRef"

    def test_no_collision_uses_leaf(self):
        """Non-colliding fields use leaf names."""
        fields = [
            ClassifiedField(field="spec.secretRef", role="input_ref", confidence=0.9,
                          field_type="object", target_kind="Secret", target_group="core"),
            ClassifiedField(field="spec.issuerRef", role="input_ref", confidence=0.9,
                          field_type="object", target_kind="Issuer"),
        ]
        result = _resolve_filenames(fields, "input_ref")
        assert result["spec.secretRef"] == "secretRef"
        assert result["spec.issuerRef"] == "issuerRef"


# ---------------------------------------------------------------------------
# Path sanitization tests
# ---------------------------------------------------------------------------


class TestPathSanitization:
    def test_dots_and_hyphens_allowed(self):
        assert _sanitize_path_segment("cert-manager.io") == "cert-manager.io"

    def test_space_replaced(self):
        assert _sanitize_path_segment("my service") == "my_service"

    def test_slash_replaced(self):
        assert _sanitize_path_segment("../evil") == ".._evil"

    def test_write_creates_directory_tree(self, populated_registry, tmp_path):
        """write_decomposed_skill creates expected directory tree."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        kind_dir = write_decomposed_skill(fixture, fields, tmp_path)

        assert (kind_dir / "manifest.json").exists()
        assert (kind_dir / "operations" / "apply.json").exists()
        assert (kind_dir / "refs").is_dir()
        assert (kind_dir / "outputs").is_dir()
        assert (kind_dir / "fields").is_dir()

    def test_output_within_output_dir(self, populated_registry, tmp_path):
        """write_decomposed_skill creates output within output_dir."""
        fixture = _load_fixture("cert-manager", "Certificate")
        fields = _classify_fixture(fixture, populated_registry)
        kind_dir = write_decomposed_skill(fixture, fields, tmp_path)
        assert kind_dir.resolve().is_relative_to(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Satisfaction mapping tests
# ---------------------------------------------------------------------------


class TestSatisfaction:
    def test_required_true(self):
        f = ClassifiedField(field="x", role="input_ref", confidence=0.9,
                          field_type="object", required=True)
        assert _satisfaction_for_field(f) == "required_value"

    def test_required_false(self):
        f = ClassifiedField(field="x", role="input_ref", confidence=0.9,
                          field_type="object", required=False)
        assert _satisfaction_for_field(f) == "optional"


# ---------------------------------------------------------------------------
# Round-trip data preservation
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.fixture(autouse=True)
    def setup(self, populated_registry):
        self.fixture = _load_fixture("cert-manager", "Certificate")
        self.fields = _classify_fixture(self.fixture, populated_registry)
        self.skill = build_decomposed_skill(self.fixture, self.fields)

    def test_all_input_refs_in_decomposed(self):
        """Every input_ref with target_kind appears in refs."""
        input_refs = [f for f in self.fields if f.role == "input_ref" and f.target_kind]
        assert len(self.skill["refs"]) == len(input_refs)

    def test_all_outputs_in_decomposed(self):
        """Every output_declaration appears in outputs."""
        outputs = [f for f in self.fields if f.role == "output_declaration"]
        assert len(self.skill["outputs"]) == len(outputs)

    def test_all_config_fields_in_decomposed(self):
        """Every config_field appears in fields."""
        config_fields = [f for f in self.fields if f.role == "config_field"]
        assert len(self.skill["fields"]) == len(config_fields)

    def test_total_count(self):
        """Total decomposed files match total classified fields."""
        total_decomposed = len(self.skill["refs"]) + len(self.skill["outputs"]) + len(self.skill["fields"])
        # Count fields that have non-None target_kind for input_refs.
        total_classified = sum(
            1 for f in self.fields
            if f.role == "config_field"
            or f.role == "output_declaration"
            or (f.role == "input_ref" and f.target_kind)
        )
        assert total_decomposed == total_classified
