"""Tests for readOnly gate G8 and self-reference config downweight (Section 04)."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency, OperationInfo
from idi.generation.dep_adapters.verify import (
    GateResult,
    _GATES,
    apply_gates,
    apply_self_reference_downweight,
    gate_g8_readonly,
)


def _dep(field: str = "f", target: str = "t", source: str = "generic_odg:body",
         confidence: float = 0.5) -> Dependency:
    return Dependency(field=field, target_resource=target, source=source,
                      confidence=confidence)


def _op(resource: str = "test", service: str = "svc") -> OperationInfo:
    return OperationInfo(
        service=service, resource=resource, operation="create",
        path=f"/{resource}", method="POST",
        body_schema={}, response_schema={},
        path_params=[], query_params=[],
    )


# ── Gate G8: readOnly Consumer Exclusion ────────────────────────────────


class TestGateG8ReadOnly:
    """Gate G8: kill body FK edges where consumer field is readOnly."""

    def test_kills_readonly_field(self):
        result = gate_g8_readonly(
            _dep(), {"type": "integer", "readOnly": True},
            {}, _op(), None,
        )
        assert result.keep is False
        assert "readOnly" in result.reason

    def test_passes_non_readonly_field(self):
        result = gate_g8_readonly(
            _dep(), {"type": "integer"},
            {}, _op(), None,
        )
        assert result.keep is True

    def test_passes_readonly_false(self):
        result = gate_g8_readonly(
            _dep(), {"type": "integer", "readOnly": False},
            {}, _op(), None,
        )
        assert result.keep is True

    def test_passes_no_schema(self):
        result = gate_g8_readonly(
            _dep(), None, {}, _op(), None,
        )
        assert result.keep is True

    def test_g8_in_gates_list(self):
        """G8 must be in the _GATES registry."""
        gate_names = [g.__name__ for g in _GATES]
        assert "gate_g8_readonly" in gate_names

    def test_g8_fires_in_apply_gates(self):
        """readOnly field killed during full apply_gates pipeline."""
        dep = _dep("auto_id", "users")
        op = _op()
        op = OperationInfo(
            service="svc", resource="test", operation="create",
            path="/test", method="POST",
            body_schema={"properties": {
                "auto_id": {"type": "integer", "readOnly": True},
            }},
            response_schema={},
            path_params=[], query_params=[],
        )
        result = apply_gates([dep], op, {})
        assert len(result) == 0  # Killed by G8


# ── Self-Reference Config Downweight ────────────────────────────────────


class TestSelfReferenceDownweight:
    """Downweight body FK edges where field is a non-identifier response property."""

    def test_config_field_downweighted(self):
        """cache_ttl on gateway response but NOT an identifier -> 0.3x."""
        deps = [_dep("cache_ttl", "gateway", confidence=0.5)]
        identifier_index = {"gateway": {"id", "gateway_id"}}
        spec = {"paths": {
            "/gateway": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "cache_ttl": {"type": "integer"},
                        "name": {"type": "string"},
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
        assert result[0].confidence == 0.15  # 0.5 * 0.3

    def test_identifier_field_exempt(self):
        """user_id -> users where 'id' is identifier -> exempt (no downweight)."""
        deps = [_dep("user_id", "users", confidence=0.5)]
        identifier_index = {"users": {"id", "user_id"}}
        spec = {"paths": {
            "/users": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "user_id": {"type": "integer"},
                        "name": {"type": "string"},
                    }},
                }}}}},
            },
        }}
        skill_paths = {
            "svc/users/list": {
                "resource": "users", "operation": "list",
                "method": "GET", "endpoint": "/users",
            },
        }
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_fk_suffixed_field_exempt(self):
        """Field with FK suffix is exempt even if it matches a response property."""
        deps = [_dep("project_id", "projects", confidence=0.5)]
        identifier_index = {"projects": {"id"}}
        spec = {"paths": {
            "/projects": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "project_id": {"type": "integer"},
                    }},
                }}}}},
            },
        }}
        skill_paths = {
            "svc/projects/list": {
                "resource": "projects", "operation": "list",
                "method": "GET", "endpoint": "/projects",
            },
        }
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        assert result[0].confidence == 0.5  # Unchanged (FK suffix exempt)

    def test_self_referential_hierarchy_exempt(self):
        """parent_id -> folders where 'id' is identifier -> exempt."""
        deps = [_dep("parent_id", "folders", confidence=0.5)]
        identifier_index = {"folders": {"id", "folder_id"}}
        spec = {"paths": {
            "/folders": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "parent_id": {"type": "integer"},
                    }},
                }}}}},
            },
        }}
        skill_paths = {
            "svc/folders/list": {
                "resource": "folders", "operation": "list",
                "method": "GET", "endpoint": "/folders",
            },
        }
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        # parent_id has _id suffix -> exempt
        assert result[0].confidence == 0.5

    def test_field_not_in_response_no_downweight(self):
        """Field NOT in target response schema -> no downweight."""
        deps = [_dep("external_ref", "items", confidence=0.5)]
        identifier_index = {"items": {"id"}}
        spec = {"paths": {
            "/items": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                    }},
                }}}}},
            },
        }}
        skill_paths = {
            "svc/items/list": {
                "resource": "items", "operation": "list",
                "method": "GET", "endpoint": "/items",
            },
        }
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_no_response_schema_no_downweight(self):
        """Target with no response schema -> no downweight."""
        deps = [_dep("cache_ttl", "items", confidence=0.5)]
        identifier_index = {"items": {"id"}}
        spec = {"paths": {}}
        skill_paths = {}
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        assert result[0].confidence == 0.5  # Unchanged

    def test_non_body_edges_not_downweighted(self):
        """Only body FK edges are candidates for downweight."""
        deps = [_dep("cache_ttl", "gateway", source="generic_odg:path", confidence=0.5)]
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
        assert result[0].confidence == 0.5  # Unchanged (not body source)

    def test_downweight_multiplier_is_0_3(self):
        """Verify 0.3 multiplier applied correctly."""
        deps = [_dep("config_val", "target", confidence=0.8)]
        identifier_index = {"target": {"id"}}
        spec = {"paths": {
            "/target": {
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"type": "object", "properties": {
                        "id": {"type": "integer"},
                        "config_val": {"type": "integer"},
                    }},
                }}}}},
            },
        }}
        skill_paths = {
            "svc/target/list": {
                "resource": "target", "operation": "list",
                "method": "GET", "endpoint": "/target",
            },
        }
        result = apply_self_reference_downweight(
            deps, identifier_index, spec, skill_paths,
        )
        assert result[0].confidence == 0.24  # 0.8 * 0.3
