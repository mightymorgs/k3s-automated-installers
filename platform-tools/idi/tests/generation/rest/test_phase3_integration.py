"""Phase 3 integration tests — verify cumulative precision improvements.

Validates:
1. All hand-crafted identifier lists removed from production code
2. Known FP patterns are killed or below confidence threshold
3. Known TP edges still survive (regression protection)
4. _NON_FK_FORMATS still present (OpenAPI standard vocabulary, allowed)
"""
from __future__ import annotations

import importlib

import pytest

from idi.generation.dep_adapters.base import Dependency, OperationInfo
from idi.generation.dep_adapters.verify import (
    apply_gates,
    build_identifier_index,
)


def _dep(field: str, target: str, source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


def _op(resource: str, service: str = "svc",
        body_schema: dict | None = None) -> OperationInfo:
    return OperationInfo(
        service=service, resource=resource, operation="create",
        path=f"/{resource}", method="POST",
        body_schema=body_schema or {},
        response_schema={},
        path_params=[], query_params=[],
    )


# ── Hand-crafted list removal audit ────────────────────────────────────


class TestHandCraftedListRemoval:
    """Verify all four hand-crafted lists are eliminated from production code."""

    def test_no_generic_identifiers_in_verify(self):
        import idi.generation.dep_adapters.verify as v
        assert not hasattr(v, "_GENERIC_IDENTIFIERS")

    def test_no_id_field_names_in_verify(self):
        import idi.generation.dep_adapters.verify as v
        assert not hasattr(v, "_ID_FIELD_NAMES")

    def test_no_common_fk_suffixes_in_target_inference(self):
        import idi.generation.dep_adapters.target_inference as ti
        assert not hasattr(ti, "_COMMON_FK_SUFFIXES")

    def test_no_never_fk_fields_in_target_inference(self):
        import idi.generation.dep_adapters.target_inference as ti
        assert not hasattr(ti, "_NEVER_FK_FIELDS")

    def test_non_fk_formats_still_present(self):
        """_NON_FK_FORMATS is OpenAPI standard vocabulary — must still exist."""
        import idi.generation.dep_adapters.target_inference as ti
        assert hasattr(ti, "_NON_FK_FORMATS")
        assert "date-time" in ti._NON_FK_FORMATS

    def test_default_fk_suffixes_exists_as_fallback(self):
        """_DEFAULT_FK_SUFFIXES exists as fallback for testing/compatibility."""
        import idi.generation.dep_adapters.target_inference as ti
        assert hasattr(ti, "_DEFAULT_FK_SUFFIXES")
        assert "_id" in ti._DEFAULT_FK_SUFFIXES


# ── FP pattern kill verification ───────────────────────────────────────


class TestFPPatternKills:
    """Verify documented FP edges are killed or below 0.25 threshold."""

    def test_config_field_fp_penalized(self):
        """Pattern A: config field (timeout, max_concurrent_jobs) penalized.

        These are non-FK-suffixed fields that shouldn't match identifiers.
        After identifier validation (0.1x), confidence drops below threshold.
        """
        deps = [
            _dep("timeout", "schedules", confidence=0.5),
            _dep("max_concurrent_jobs", "instance-groups", confidence=0.5),
        ]
        identifier_index = {
            "schedules": {"id", "schedule_id"},
            "instance-groups": {"id"},
        }
        from idi.generation.dep_adapters.verify import apply_identifier_validation
        result = apply_identifier_validation(deps, identifier_index)
        for d in result:
            assert d.confidence < 0.25, f"{d.field} should be below threshold"

    def test_self_reference_config_fp_downweighted(self):
        """Pattern B: self-reference config fields downweighted.

        Fields like cache_ttl that exist on the target's response but
        are not identifiers get a 0.3x multiplier.
        """
        from idi.generation.dep_adapters.verify import apply_self_reference_downweight
        deps = [_dep("cache_ttl", "gateway", confidence=0.5)]
        identifier_index = {"gateway": {"id"}}
        spec = {"paths": {
            "/gateway": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "cache_ttl": {"type": "integer"},
                    }},
                }}}}},
            },
        }}
        skill_paths = {
            "svc/gateway/list": {
                "resource": "gateway", "operation": "list",
                "method": "GET", "endpoint": "/gateway",
            },
        }
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        assert result[0].confidence < 0.25


# ── TP preservation regression ─────────────────────────────────────────


class TestTPPreservation:
    """Known true positive edges must survive all gates."""

    def test_user_id_to_users_survives(self):
        """user_id -> users is a classic TP that must not be killed."""
        deps = [_dep("user_id", "users", confidence=0.6)]
        identifier_index = {
            "users": {"id", "user_id"},
            "items": {"id"},
        }
        from idi.generation.dep_adapters.verify import apply_identifier_validation
        result = apply_identifier_validation(deps, identifier_index)
        assert result[0].confidence == 0.6  # Unchanged

    def test_series_id_to_series_survives(self):
        """series_id -> series survives identifier validation."""
        deps = [_dep("series_id", "series", confidence=0.6)]
        identifier_index = {"series": {"id", "series_id"}}
        from idi.generation.dep_adapters.verify import apply_identifier_validation
        result = apply_identifier_validation(deps, identifier_index)
        assert result[0].confidence == 0.6

    def test_fk_suffixed_field_survives_gates(self):
        """FK-suffixed fields pass through all gates."""
        dep = _dep("project_id", "projects", confidence=0.6)
        op = _op("test", body_schema={"properties": {
            "project_id": {"type": "integer"},
        }})
        result = apply_gates([dep], op, {})
        assert len(result) == 1
        assert result[0].field == "project_id"

    def test_generic_id_field_survives(self):
        """'id' field as a generic identifier passes when stem is widespread."""
        deps = [_dep("id", "target_resource", confidence=0.6)]
        identifier_index = {
            "target_resource": {"slug"},
            "users": {"id"},
            "items": {"id"},
        }
        from idi.generation.dep_adapters.verify import apply_identifier_validation
        result = apply_identifier_validation(deps, identifier_index)
        assert result[0].confidence == 0.6  # Generic ID passes


# ── Phase 3 new feature smoke tests ────────────────────────────────────


class TestPhase3NewFeatures:
    """Smoke tests for all Phase 3 features working together."""

    def test_canonical_map_exists(self):
        """CanonicalResourceMap can be imported and built."""
        from idi.generation.dep_adapters.canonical_resources import (
            build_canonical_resource_map,
        )
        spec = {"paths": {"/users/{user_id}": {"get": {}}}}
        cmap = build_canonical_resource_map(spec)
        assert cmap.canonicalize("users") == "users"

    def test_learn_fk_suffixes_works(self):
        """FK suffix learning produces results from spec."""
        from idi.generation.dep_adapters.canonical_resources import (
            build_canonical_resource_map,
            learn_fk_suffixes,
        )
        spec = {"paths": {
            "/users/{user_id}": {"get": {}},
            "/items/{item_id}": {"get": {}},
        }}
        cmap = build_canonical_resource_map(spec)
        suffixes = learn_fk_suffixes(spec, cmap)
        assert len(suffixes) > 0

    def test_gate_g8_readonly_in_pipeline(self):
        """G8 gate is registered and fires in pipeline."""
        from idi.generation.dep_adapters.verify import _GATES
        gate_names = [g.__name__ for g in _GATES]
        assert "gate_g8_readonly" in gate_names

    def test_all_gates_registered(self):
        """All 8 gates are in the registry."""
        from idi.generation.dep_adapters.verify import _GATES
        assert len(_GATES) == 8
