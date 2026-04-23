"""Tests for helm enrichment (Stage 4)."""
from __future__ import annotations

from typing import Any

import pytest

from idi.generation.helm.context import HelmContext
from idi.generation.helm.enrichment import enrich_facts
from idi.generation.helm.models import AnnotationInfo, HelmFact, SchemaInfo


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


def _ctx(**kw: Any) -> HelmContext:
    defaults = dict(
        chart_name="test", chart_version="1.0", app_version="1.0",
        repository="", values={}, chart_meta={}, values_text="",
        kind_registry=None,
    )
    defaults.update(kw)
    return HelmContext(**defaults)


def _schema(**kw: Any) -> SchemaInfo:
    defaults = dict(type=None, format=None, enum=None, required=False,
                    description=None, default=None, write_only=False, pattern=None)
    defaults.update(kw)
    return SchemaInfo(**defaults)


class TestSchemaOverrides:
    def test_type_override(self):
        f = _fact(path_segments=["port"], semantic_type="string")
        ctx = _ctx(schema_overrides={("port",): _schema(type="integer")})
        enrich_facts([f], ctx)
        assert f.semantic_type == "integer"

    def test_enum_override(self):
        f = _fact(path_segments=["mode"])
        ctx = _ctx(schema_overrides={("mode",): _schema(enum=["a", "b"])})
        enrich_facts([f], ctx)
        assert f.enum == ["a", "b"]

    def test_required_override(self):
        f = _fact(path_segments=["key"])
        ctx = _ctx(schema_overrides={("key",): _schema(required=True)})
        enrich_facts([f], ctx)
        assert f.required is True

    def test_description_override(self):
        f = _fact(path_segments=["key"])
        ctx = _ctx(schema_overrides={("key",): _schema(description="Schema desc")})
        enrich_facts([f], ctx)
        assert f.description == "Schema desc"

    def test_format_override(self):
        f = _fact(path_segments=["key"])
        ctx = _ctx(schema_overrides={("key",): _schema(format="uri")})
        enrich_facts([f], ctx)
        assert f.format == "uri"

    def test_type_override_logs_classification(self):
        f = _fact(path_segments=["port"], semantic_type="string", classifications=[])
        ctx = _ctx(schema_overrides={("port",): _schema(type="integer")})
        enrich_facts([f], ctx)
        override_cls = [c for c in f.classifications if c.method == "schema_type_override"]
        assert len(override_cls) == 1


class TestAnnotationOverrides:
    def test_description_fills_in(self):
        f = _fact(path_segments=["key"], source="kind_registry")
        ctx = _ctx(annotations={("key",): AnnotationInfo(type=None, description="Annot desc", enum=None, source="bitnami_param")})
        enrich_facts([f], ctx)
        assert f.description == "Annot desc"

    def test_description_does_not_override_schema(self):
        f = _fact(path_segments=["key"], description="Schema desc")
        ctx = _ctx(
            schema_overrides={("key",): _schema(description="Schema desc")},
            annotations={("key",): AnnotationInfo(type=None, description="Annot desc", enum=None, source="bitnami_param")},
        )
        enrich_facts([f], ctx)
        assert f.description == "Schema desc"

    def test_enum_fills_in(self):
        f = _fact(path_segments=["mode"], source="kind_registry")
        ctx = _ctx(annotations={("mode",): AnnotationInfo(type=None, description=None, enum=["x", "y"], source="dadav_schema")})
        enrich_facts([f], ctx)
        assert f.enum == ["x", "y"]

    def test_enum_does_not_override_existing(self):
        f = _fact(path_segments=["mode"], enum=["a", "b"])
        ctx = _ctx(annotations={("mode",): AnnotationInfo(type=None, description=None, enum=["x", "y"], source="dadav_schema")})
        enrich_facts([f], ctx)
        assert f.enum == ["a", "b"]

    def test_type_applies_for_heuristic_keyword(self):
        f = _fact(path_segments=["val"], source="heuristic_keyword")
        ctx = _ctx(annotations={("val",): AnnotationInfo(type="integer", description=None, enum=None, source="bitnami_param")})
        enrich_facts([f], ctx)
        assert f.semantic_type == "integer"

    def test_type_applies_for_heuristic_default(self):
        f = _fact(path_segments=["val"], source="heuristic_default")
        ctx = _ctx(annotations={("val",): AnnotationInfo(type="boolean", description=None, enum=None, source="helm_docs")})
        enrich_facts([f], ctx)
        assert f.semantic_type == "boolean"

    def test_type_does_not_apply_for_structural_source(self):
        f = _fact(path_segments=["val"], source="kind_registry", semantic_type="string")
        ctx = _ctx(annotations={("val",): AnnotationInfo(type="integer", description=None, enum=None, source="bitnami_param")})
        enrich_facts([f], ctx)
        assert f.semantic_type == "string"

    def test_type_does_not_apply_for_schema_source(self):
        f = _fact(path_segments=["val"], source="schema_format", semantic_type="string")
        ctx = _ctx(annotations={("val",): AnnotationInfo(type="integer", description=None, enum=None, source="bitnami_param")})
        enrich_facts([f], ctx)
        assert f.semantic_type == "string"


class TestSchemaVsAnnotation:
    def test_schema_takes_priority(self):
        f = _fact(path_segments=["key"])
        ctx = _ctx(
            schema_overrides={("key",): _schema(description="Schema", enum=["s1"])},
            annotations={("key",): AnnotationInfo(type=None, description="Annot", enum=["a1"], source="bitnami_param")},
        )
        enrich_facts([f], ctx)
        assert f.description == "Schema"
        assert f.enum == ["s1"]


class TestNoOverrides:
    def test_fact_unchanged(self):
        f = _fact(path_segments=["unknown"], description=None, enum=None)
        ctx = _ctx()
        enrich_facts([f], ctx)
        assert f.description is None
        assert f.enum is None

    def test_conditional_on_unchanged(self):
        f = _fact(path_segments=["key"])
        ctx = _ctx()
        enrich_facts([f], ctx)
        assert f.conditional_on is None
        assert f.feature is None
