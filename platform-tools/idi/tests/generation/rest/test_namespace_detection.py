"""Tests for section-08: Statistical namespace detection.

Detects routing/namespace path parameters from spec structure using
frequency (≥30% of ops) and dispersion (≥5 distinct children) thresholds.
"""
from __future__ import annotations

import pytest

from idi.generation.dep_adapters.base import OperationInfo
from idi.generation.dep_adapters.path_deps import detect_namespace_params, detect_path_deps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_spec(paths: dict[str, list[str]]) -> dict:
    """Build a minimal OpenAPI spec from a {path: [methods]} mapping."""
    spec_paths = {}
    for path, methods in paths.items():
        spec_paths[path] = {m: {"responses": {"200": {}}} for m in methods}
    return {"paths": spec_paths}


def _op(
    path: str,
    resource: str = "things",
    service: str = "test",
    namespace_params: frozenset[str] | None = None,
    path_param_schemas: dict | None = None,
) -> OperationInfo:
    return OperationInfo(
        path=path,
        method="GET",
        operation=f"GET {path}",
        resource=resource,
        service=service,
        body_schema={},
        response_schema={},
        namespace_params=namespace_params or frozenset(),
        path_param_schemas=path_param_schemas or {},
    )


# ---------------------------------------------------------------------------
# detect_namespace_params tests
# ---------------------------------------------------------------------------

class TestDetectNamespaceParams:
    """Statistical detection of namespace/routing path parameters."""

    def test_high_frequency_high_dispersion_detected(self):
        """Param in 80% of ops with 20 distinct children → namespace."""
        paths = {}
        for i in range(20):
            paths[f"/api/{{realm}}/resource{i}"] = ["get"]
        paths["/api/health"] = ["get"]
        paths["/api/version"] = ["get"]
        paths["/api/metrics"] = ["get"]
        paths["/api/status"] = ["get"]
        paths["/api/info"] = ["get"]
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert "realm" in ns

    def test_low_frequency_not_detected(self):
        """Param in 10% of ops → NOT namespace (low frequency)."""
        paths = {}
        # 2 ops with {tenant}, 18 without
        paths["/api/{tenant}/resource1"] = ["get"]
        paths["/api/{tenant}/resource2"] = ["get"]
        for i in range(18):
            paths[f"/api/resource{i + 3}"] = ["get"]
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert "tenant" not in ns

    def test_high_frequency_low_dispersion_not_detected(self):
        """Param in 50% of ops with only 2 distinct children → NOT namespace."""
        paths = {}
        # Same 2 children repeated many times (different methods)
        for method in ["get", "post", "put", "delete"]:
            paths.setdefault("/api/{org}/users", []).append(method)
            paths.setdefault("/api/{org}/teams", []).append(method)
        # Add some ops without {org}
        for method in ["get", "post", "put", "delete"]:
            paths.setdefault("/api/health", []).append(method)
            paths.setdefault("/api/version", []).append(method)
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert "org" not in ns

    def test_keycloak_realm_detected(self):
        """Keycloak-like spec with {realm} in most paths → detected."""
        paths = {}
        children = [
            "users", "groups", "roles", "clients", "client-scopes",
            "identity-providers", "authentication", "components",
            "realms", "sessions", "events",
        ]
        for child in children:
            paths[f"/admin/realms/{{realm}}/{child}"] = ["get", "post"]
            paths[f"/admin/realms/{{realm}}/{child}/{{id}}"] = ["get", "put", "delete"]
        # A few non-realm paths
        paths["/admin/serverinfo"] = ["get"]
        paths["/admin/realms"] = ["get", "post"]
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert "realm" in ns

    def test_vault_mount_path_not_detected(self):
        """Vault {pki_mount_path} in ~15% of paths → NOT namespace."""
        paths = {}
        # 5 paths with mount_path
        for child in ["issue", "sign", "revoke", "tidy", "config"]:
            paths[f"/v1/{{pki_mount_path}}/{child}"] = ["post"]
        # 30 paths without
        for i in range(30):
            paths[f"/v1/sys/resource{i}"] = ["get"]
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert "pki_mount_path" not in ns

    def test_multiple_namespace_params_detected(self):
        """Two high-frequency high-dispersion params both detected."""
        paths = {}
        children = ["a", "b", "c", "d", "e", "f"]
        for child in children:
            paths[f"/api/{{org}}/{{realm}}/{child}"] = ["get", "post"]
        # A few extra without either
        paths["/api/health"] = ["get"]
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert "org" in ns
        assert "realm" in ns

    def test_no_high_frequency_params_empty_set(self):
        """Spec with no high-frequency params → empty namespace set."""
        paths = {
            "/api/users": ["get", "post"],
            "/api/users/{user_id}": ["get", "put"],
            "/api/teams": ["get", "post"],
            "/api/teams/{team_id}": ["get", "put"],
        }
        spec = _build_spec(paths)
        ns = detect_namespace_params(spec)
        assert len(ns) == 0


# ---------------------------------------------------------------------------
# Integration with detect_path_deps
# ---------------------------------------------------------------------------

class TestNamespaceExclusionInPathDeps:
    """Namespace params are excluded from path dep detection."""

    def test_namespace_param_excluded(self):
        """Path param in namespace_params does not produce an edge."""
        op = _op(
            path="/admin/realms/{realm}/users/{user_id}",
            resource="users",
            namespace_params=frozenset({"realm"}),
        )
        deps = detect_path_deps(op, {"realms", "users"})
        targets = {d.target_resource for d in deps}
        assert "realms" not in targets

    def test_non_namespace_param_still_processed(self):
        """Non-namespace params still produce edges normally."""
        op = _op(
            path="/admin/realms/{realm}/users/{user_id}",
            resource="users",
            namespace_params=frozenset({"realm"}),
        )
        deps = detect_path_deps(op, {"realms", "users"})
        targets = {d.target_resource for d in deps}
        assert "users" in targets

    def test_base_excluded_set_still_applied(self):
        """The base _EXCLUDED set (namespace, ns) still works."""
        op = _op(
            path="/api/{namespace}/pods/{pod_id}",
            resource="pods",
            namespace_params=frozenset(),  # No detected namespaces
        )
        deps = detect_path_deps(op, {"namespaces", "pods"})
        targets = {d.target_resource for d in deps}
        assert "namespaces" not in targets
