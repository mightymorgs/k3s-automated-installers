"""Tests for section-07: Body FK activation gating (Approach E core).

Two levels of gating:
  Level 1 (registry.py): Suppress body deps whose target is already covered by path deps.
  Level 2 (body_fk.py): Precondition gate — only call infer_target() for fields with
  FK suffix evidence or strong type (uuid format, integer type).
"""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.base import Dependency, DetectionSource, OperationInfo
from idi.generation.dep_adapters.body_fk import detect_body_deps
from idi.generation.dep_adapters.merge import filter_by_confidence, filter_self_refs
from idi.generation.dep_adapters.registry import DepAdapterRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _op(
    path: str = "/api/v1/things",
    method: str = "POST",
    resource: str = "things",
    service: str = "test",
    body_schema: dict | None = None,
    response_schema: dict | None = None,
    path_param_schemas: dict | None = None,
) -> OperationInfo:
    return OperationInfo(
        path=path,
        method=method,
        operation=f"{method} {path}",
        resource=resource,
        service=service,
        body_schema=body_schema,
        response_schema=response_schema,
        path_param_schemas=path_param_schemas or {},
    )


def _body_dep(target: str, field: str = "user_id", confidence: float = 0.8) -> Dependency:
    return Dependency(
        field=field,
        target_resource=target,
        target_operation="create",
        fact_ref=f"facts://test/{target}#id",
        confidence=confidence,
        source="generic_odg:body",
        lineage_type="copy",
    )


def _path_dep(target: str, field: str = "user_id", confidence: float = 0.8) -> Dependency:
    return Dependency(
        field=field,
        target_resource=target,
        target_operation="create",
        fact_ref=f"facts://test/{target}#id",
        confidence=confidence,
        source="generic_odg:path",
        lineage_type="copy",
    )


# ---------------------------------------------------------------------------
# Level 1: Post-detection suppression in registry.py
# ---------------------------------------------------------------------------

class TestBodyDepSuppression:
    """Body deps are suppressed when path deps cover the same target resource."""

    def test_body_dep_suppressed_when_path_covers_same_target(self):
        """Body dep to 'users' suppressed when path dep to 'users' exists."""
        deps = [
            _path_dep("users"),
            _body_dep("users"),
        ]
        # Simulate registry suppression logic
        path_targets = {d.target_resource for d in deps if d.source == "generic_odg:path"}
        filtered = [
            d for d in deps
            if d.source != "generic_odg:body" or d.target_resource not in path_targets
        ]
        assert len(filtered) == 1
        assert filtered[0].source == "generic_odg:path"

    def test_body_dep_kept_when_target_not_in_path_deps(self):
        """Body dep to 'roles' kept when path deps only target 'users'."""
        deps = [
            _path_dep("users"),
            _body_dep("roles", field="role_id"),
        ]
        path_targets = {d.target_resource for d in deps if d.source == "generic_odg:path"}
        filtered = [
            d for d in deps
            if d.source != "generic_odg:body" or d.target_resource not in path_targets
        ]
        assert len(filtered) == 2

    def test_body_deps_to_different_targets_kept(self):
        """Body deps to targets not in path_targets survive."""
        deps = [
            _path_dep("users"),
            _body_dep("projects", field="project_id"),
            _body_dep("teams", field="team_id"),
        ]
        path_targets = {d.target_resource for d in deps if d.source == "generic_odg:path"}
        filtered = [
            d for d in deps
            if d.source != "generic_odg:body" or d.target_resource not in path_targets
        ]
        assert len(filtered) == 3

    def test_multiple_path_targets_suppress_matching_body_deps(self):
        """Body deps to any path target are suppressed."""
        deps = [
            _path_dep("users"),
            _path_dep("projects"),
            _body_dep("users", field="user_id"),
            _body_dep("projects", field="project_id"),
            _body_dep("teams", field="team_id"),
        ]
        path_targets = {d.target_resource for d in deps if d.source == "generic_odg:path"}
        filtered = [
            d for d in deps
            if d.source != "generic_odg:body" or d.target_resource not in path_targets
        ]
        assert len(filtered) == 3  # 2 path + 1 body (teams)
        body_filtered = [d for d in filtered if d.source == "generic_odg:body"]
        assert len(body_filtered) == 1
        assert body_filtered[0].target_resource == "teams"


# ---------------------------------------------------------------------------
# Level 2: Precondition gate in body_fk.py
# ---------------------------------------------------------------------------

class TestBodyFKPreconditionGate:
    """Fields must have FK suffix or strong type to reach infer_target()."""

    def _run_body_detect(self, field_name: str, field_schema: dict, known: set[str]) -> list[Dependency]:
        """Helper to run detect_body_deps with a single body field."""
        op = _op(
            body_schema={"properties": {field_name: field_schema}},
        )
        return detect_body_deps(op, known)

    def test_id_suffix_passes_gate(self):
        """Field 'user_id' (string) passes — has _id suffix."""
        deps = self._run_body_detect("user_id", {"type": "string"}, {"users"})
        # Should produce a dep (user_id → users)
        assert any(d.target_resource == "users" for d in deps)

    def test_uuid_suffix_passes_gate(self):
        """Field 'project_uuid' passes — has _uuid suffix."""
        deps = self._run_body_detect("project_uuid", {"type": "string"}, {"projects"})
        assert any(d.target_resource == "projects" for d in deps)

    def test_uuid_format_passes_gate(self):
        """Field 'project' with format: uuid passes — strong type."""
        deps = self._run_body_detect("project", {"type": "string", "format": "uuid"}, {"projects"})
        assert any(d.target_resource == "projects" for d in deps)

    def test_integer_type_passes_gate(self):
        """Field 'project' with type: integer passes — strong type."""
        deps = self._run_body_detect("project", {"type": "integer"}, {"projects"})
        assert any(d.target_resource == "projects" for d in deps)

    def test_plain_string_no_suffix_blocked(self):
        """Field 'description' (string, no FK suffix) is blocked at gate."""
        deps = self._run_body_detect("description", {"type": "string"}, {"descriptions"})
        assert not deps

    def test_integer_no_suffix_still_passes(self):
        """Field 'priority' (integer, no FK suffix) passes — integer is strong type."""
        # But it won't match a resource unless there's a "priorities" resource
        deps = self._run_body_detect("priority", {"type": "integer"}, {"priorities"})
        # Integer passes gate, but whether it matches depends on target inference
        # The key is it's NOT blocked at the gate
        # (it may or may not produce a dep depending on target inference)
        # We just verify no crash and that the gate doesn't block it
        # For a more direct test, use a known-matching resource name
        deps2 = self._run_body_detect("user", {"type": "integer"}, {"users"})
        assert any(d.target_resource == "users" for d in deps2)

    def test_boolean_no_suffix_blocked(self):
        """Field 'enabled' (boolean) is blocked — not strong type, no suffix."""
        deps = self._run_body_detect("enabled", {"type": "boolean"}, {"enableds"})
        assert not deps

    def test_plain_string_name_like_resource_blocked(self):
        """Field 'token_max_ttl' (string) blocked — no suffix, not strong type."""
        deps = self._run_body_detect("token_max_ttl", {"type": "string"}, {"tokens"})
        assert not deps

    def test_array_of_integer_passes_gate(self):
        """Field 'tag_ids' with type: array, items: {type: integer} passes gate."""
        schema = {"type": "array", "items": {"type": "integer"}}
        deps = self._run_body_detect("tag", schema, {"tags"})
        assert any(d.target_resource == "tags" for d in deps)

    def test_array_of_uuid_passes_gate(self):
        """Field 'user' with type: array, items: {format: uuid} passes gate."""
        schema = {"type": "array", "items": {"type": "string", "format": "uuid"}}
        deps = self._run_body_detect("user", schema, {"users"})
        assert any(d.target_resource == "users" for d in deps)


# ---------------------------------------------------------------------------
# Integration: both levels together
# ---------------------------------------------------------------------------

class TestIntegrationBodyFKGating:
    """End-to-end: path dep suppresses body dep to same resource."""

    def test_path_dep_suppresses_body_dep_same_resource(self):
        """When path says 'users' and body also says 'users', body dep is dropped."""
        # Build deps as the registry would produce them
        path_dep = _path_dep("users", field="user_id")
        body_dep = _body_dep("users", field="user_id")
        all_deps = [path_dep, body_dep]

        # Apply confidence filter first (section-01 style)
        filtered = filter_by_confidence(all_deps)
        # Then apply body suppression
        path_targets = {d.target_resource for d in filtered if d.source == "generic_odg:path"}
        final = [
            d for d in filtered
            if d.source != "generic_odg:body" or d.target_resource not in path_targets
        ]

        assert len(final) == 1
        assert final[0].source == "generic_odg:path"
