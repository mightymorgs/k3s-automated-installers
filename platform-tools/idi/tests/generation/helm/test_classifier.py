"""Tests for helm classifier (Stage 3 — 5-tier cascade)."""
from __future__ import annotations

from typing import Any

import pytest

from idi.generation.helm.classifier import (
    build_fact_index,
    classify_facts,
    get_descendants,
    get_siblings,
    is_descendant_of,
    resolve_winner,
)
from idi.generation.helm.context import HelmContext
from idi.generation.helm.models import (
    AnnotationInfo,
    Classification,
    HelmFact,
    SchemaInfo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fact(**kw: Any) -> HelmFact:
    defaults = dict(
        path="x", path_segments=["x"], uri="", default_value="",
        type="string", semantic_type="string", has_template=False,
        default_empty=True, default_truncated=False, shape="config",
        format=None, required=False, enum=None, description=None,
        is_toggle=False, conditional_on=None, feature=None,
        cross_app_signal=None, classifications=[], source="heuristic_default",
        confidence=0.50, needs_review=True,
    )
    defaults.update(kw)
    if "path_segments" in kw and "path" not in kw:
        defaults["path"] = ".".join(kw["path_segments"])
    return HelmFact(**defaults)


class MockKindRegistry:
    """Minimal KindRegistry mock for testing."""
    _KNOWN = {
        "secretname": (True, "Secret", "secrets", "core"),
        "configmapref": (True, "ConfigMap", "configmaps", "core"),
        "serviceaccountname": (True, "ServiceAccount", "serviceaccounts", "core"),
        "claimname": (True, "PersistentVolumeClaim", "persistentvolumeclaims", "core"),
    }

    def is_ref_field(self, field_name: str, current_group: str = "") -> tuple[bool, str | None, str | None, str | None]:
        result = self._KNOWN.get(field_name.lower())
        if result:
            return result
        return (False, None, None, None)


def _ctx(facts: list[HelmFact], **kw: Any) -> HelmContext:
    defaults = dict(
        chart_name="test", chart_version="1.0", app_version="1.0",
        repository="", values={}, chart_meta={}, values_text="",
        kind_registry=MockKindRegistry(),
        schema_overrides={}, annotations={}, chart_conditions={},
    )
    defaults.update(kw)
    ctx = HelmContext(**defaults)
    ctx.facts = facts
    return ctx


# ---------------------------------------------------------------------------
# Fact Index
# ---------------------------------------------------------------------------

class TestFactIndex:
    def test_siblings_grouped_by_parent(self):
        facts = [
            _fact(path_segments=["a", "x"]),
            _fact(path_segments=["a", "y"]),
            _fact(path_segments=["b", "z"]),
        ]
        idx = build_fact_index(facts)
        siblings = get_siblings(facts[0], idx)
        assert len(siblings) == 1
        assert siblings[0].path_segments == ["a", "y"]

    def test_siblings_excludes_self(self):
        f = _fact(path_segments=["a", "x"])
        facts = [f, _fact(path_segments=["a", "y"])]
        idx = build_fact_index(facts)
        siblings = get_siblings(f, idx)
        assert f not in siblings

    def test_descendants(self):
        facts = [
            _fact(path_segments=["a", "b"]),
            _fact(path_segments=["a", "b", "c"]),
            _fact(path_segments=["a", "b", "c", "d"]),
            _fact(path_segments=["a", "x"]),
        ]
        desc = get_descendants(["a", "b"], facts)
        assert len(desc) == 2

    def test_is_descendant_of_false_for_equal(self):
        f = _fact(path_segments=["a", "b"])
        assert is_descendant_of(f, ["a", "b"]) is False

    def test_is_descendant_of_true(self):
        f = _fact(path_segments=["a", "b", "c"])
        assert is_descendant_of(f, ["a", "b"]) is True


# ---------------------------------------------------------------------------
# Winner resolution
# ---------------------------------------------------------------------------

class TestResolveWinner:
    def test_picks_highest_confidence(self):
        cs = [
            Classification("shape", "config", "heuristic_keyword", 0.50, ""),
            Classification("shape", "credential", "schema_format", 0.95, ""),
        ]
        assert resolve_winner(cs, "shape") == "credential"

    def test_no_classifications_returns_none(self):
        assert resolve_winner([], "shape") is None

    def test_ignores_other_fields(self):
        cs = [
            Classification("is_toggle", "true", "boolean_with_children", 0.80, ""),
            Classification("shape", "config", "heuristic_default", 0.50, ""),
        ]
        assert resolve_winner(cs, "shape") == "config"


# ---------------------------------------------------------------------------
# Tier A: Schema-derived
# ---------------------------------------------------------------------------

class TestTierA:
    def test_format_password_credential(self):
        f = _fact(path_segments=["auth", "pw"])
        schema = {("auth", "pw"): SchemaInfo(type="string", format="password", enum=None,
                  required=False, description=None, default=None, write_only=False, pattern=None)}
        ctx = _ctx([f], schema_overrides=schema)
        classify_facts([f], ctx)
        assert f.shape == "credential"
        assert f.confidence == 0.95

    def test_format_uri_addressability(self):
        f = _fact(path_segments=["server", "url"])
        schema = {("server", "url"): SchemaInfo(type="string", format="uri", enum=None,
                  required=False, description=None, default=None, write_only=False, pattern=None)}
        ctx = _ctx([f], schema_overrides=schema)
        classify_facts([f], ctx)
        assert f.shape == "addressability"

    def test_write_only_credential(self):
        f = _fact(path_segments=["key"])
        schema = {("key",): SchemaInfo(type="string", format=None, enum=None,
                  required=False, description=None, default=None, write_only=True, pattern=None)}
        ctx = _ctx([f], schema_overrides=schema)
        classify_facts([f], ctx)
        assert f.shape == "credential"

    def test_boolean_type_config(self):
        f = _fact(path_segments=["debug"], default_value=True, type="boolean")
        schema = {("debug",): SchemaInfo(type="boolean", format=None, enum=None,
                  required=False, description=None, default=None, write_only=False, pattern=None)}
        ctx = _ctx([f], schema_overrides=schema)
        classify_facts([f], ctx)
        assert f.shape == "config"


# ---------------------------------------------------------------------------
# Tier B: Chart.yaml
# ---------------------------------------------------------------------------

class TestTierB:
    def test_chartmeta_condition_toggle(self):
        f = _fact(path_segments=["postgresql", "enabled"], default_value=True, type="boolean")
        ctx = _ctx([f], chart_conditions={"postgresql": "postgresql.enabled"})
        classify_facts([f], ctx)
        assert f.is_toggle is True


# ---------------------------------------------------------------------------
# Tier C: Structural
# ---------------------------------------------------------------------------

class TestTierC:
    def test_c1_secretname_identity(self):
        f = _fact(path_segments=["tls", "secretName"], default_value="my-secret")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.shape == "identity"
        assert f.confidence == 0.90

    def test_c2_reference_tuple(self):
        f = _fact(path_segments=["ref"], default_value={"name": "x", "namespace": "y"},
                  type="object")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.shape == "identity"

    def test_c3_credential_with_existing_sibling(self):
        pw = _fact(path_segments=["auth", "password"], default_value="", type="string")
        existing = _fact(path_segments=["auth", "existingSecret"], default_value="", type="string")
        ctx = _ctx([pw, existing])
        classify_facts([pw, existing], ctx)
        assert pw.shape == "credential"

    def test_c3_non_credential_with_existing_sibling(self):
        db = _fact(path_segments=["auth", "database"], default_value="mydb", type="string")
        existing = _fact(path_segments=["auth", "existingSecret"], default_value="", type="string")
        ctx = _ctx([db, existing])
        classify_facts([db, existing], ctx)
        # "database" is not in CREDENTIAL_LEAF_KEYS, so it gets config at 0.65
        shape_cls = [c for c in db.classifications if c.field == "shape" and c.method == "sibling_secret_binding"]
        assert len(shape_cls) == 1
        assert shape_cls[0].confidence == 0.65

    def test_c5_url_value(self):
        f = _fact(path_segments=["endpoint"], default_value="https://example.com")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.shape == "addressability"

    def test_c6_port_in_service_context(self):
        f = _fact(path_segments=["service", "port"], default_value=8200, type="integer")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.shape == "addressability"

    def test_c6_port_without_service_context(self):
        f = _fact(path_segments=["config", "maxRetries"], default_value=3, type="integer")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        # No service context, should not be classified as addressability by port range
        port_cls = [c for c in f.classifications if c.method == "value_port_range"]
        assert len(port_cls) == 0

    def test_c7_endpoint_tuple(self):
        host = _fact(path_segments=["db", "host"], default_value="localhost")
        port = _fact(path_segments=["db", "port"], default_value=5432, type="integer")
        ctx = _ctx([host, port])
        classify_facts([host, port], ctx)
        # At least one should get endpoint_tuple classification
        et_cls = [c for c in host.classifications if c.method == "endpoint_tuple"]
        assert len(et_cls) == 1

    def test_c8_boolean_toggle(self):
        toggle = _fact(path_segments=["server", "enabled"], default_value=True, type="boolean")
        child1 = _fact(path_segments=["server", "port"], default_value=8080, type="integer")
        child2 = _fact(path_segments=["server", "host"], default_value="0.0.0.0")
        ctx = _ctx([toggle, child1, child2])
        classify_facts([toggle, child1, child2], ctx)
        assert toggle.is_toggle is True

    def test_c8_no_toggle_without_descendants(self):
        toggle = _fact(path_segments=["enabled"], default_value=True, type="boolean")
        ctx = _ctx([toggle])
        classify_facts([toggle], ctx)
        assert toggle.is_toggle is False

    def test_c9_existing_secret_signal(self):
        f = _fact(path_segments=["auth", "existingSecret"], default_value="", type="string")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.cross_app_signal == "secret_binding"

    def test_c9_existing_claim_signal(self):
        f = _fact(path_segments=["persistence", "existingClaim"], default_value="", type="string")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.cross_app_signal == "pvc_binding"

    def test_c10_external_host_signal(self):
        f = _fact(path_segments=["externalDatabase", "host"], default_value="")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.cross_app_signal == "external_service_dependency"


# ---------------------------------------------------------------------------
# Tier D: Annotation-derived
# ---------------------------------------------------------------------------

class TestTierD:
    def test_annotation_type(self):
        f = _fact(path_segments=["name"])
        annot = {("name",): AnnotationInfo(type="string", description=None, enum=None, source="bitnami_param")}
        ctx = _ctx([f], annotations=annot)
        classify_facts([f], ctx)
        assert f.semantic_type == "string"


# ---------------------------------------------------------------------------
# Tier E: Heuristic
# ---------------------------------------------------------------------------

class TestTierE:
    def test_heuristic_when_no_higher_tier(self):
        f = _fact(path_segments=["replicaCount"], default_value=3, type="integer")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.shape == "config"
        assert f.source == "heuristic_keyword"
        assert f.confidence == 0.50

    def test_no_heuristic_when_higher_tier_exists(self):
        f = _fact(path_segments=["tls", "secretName"], default_value="my-secret")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        # secretName matches kind_registry (Tier C) — heuristic should not run
        heuristic_cls = [c for c in f.classifications
                         if c.method in ("heuristic_keyword", "heuristic_default")]
        assert len(heuristic_cls) == 0

    def test_needs_review_for_low_confidence(self):
        f = _fact(path_segments=["unknownThing"], default_value="foo")
        ctx = _ctx([f])
        classify_facts([f], ctx)
        assert f.confidence == 0.50
        assert f.needs_review is True
