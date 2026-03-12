"""Tests for test infrastructure: golden files, fixtures, and helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.generation.crd.conftest import assert_json_equivalent, _FIXTURES_DIR, _GOLDEN_DIR


# ---------------------------------------------------------------------------
# Golden file validation
# ---------------------------------------------------------------------------

_EXPECTED_SERVICES = {"cert-manager", "external-secrets", "traefik"}
_EXPECTED_KINDS = {
    "cert-manager": {
        "Certificate", "CertificateRequest", "Issuer", "ClusterIssuer",
        "Order", "Challenge",
    },
    "external-secrets": {
        "ExternalSecret", "SecretStore", "ClusterSecretStore",
        "ClusterExternalSecret", "PushSecret",
    },
    "traefik": {
        "IngressRoute", "IngressRouteTCP", "IngressRouteUDP",
        "Middleware", "MiddlewareTCP", "ServersTransport",
        "ServersTransportTCP", "TLSOption", "TLSStore", "TraefikService",
    },
}


def test_golden_files_exist():
    """golden_files directory contains exactly 21 JSON files across 3 subdirectories."""
    assert _GOLDEN_DIR.is_dir(), f"golden_files dir not found: {_GOLDEN_DIR}"
    all_json = list(_GOLDEN_DIR.rglob("*.json"))
    assert len(all_json) == 21, f"Expected 21 golden files, found {len(all_json)}"
    subdirs = {p.name for p in _GOLDEN_DIR.iterdir() if p.is_dir()}
    assert subdirs == _EXPECTED_SERVICES


def test_golden_files_valid_json():
    """Each golden file is valid JSON and has schema_version '1.0'."""
    for json_path in sorted(_GOLDEN_DIR.rglob("*.json")):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data.get("schema_version") == "1.0", (
            f"{json_path.name}: expected schema_version '1.0', got {data.get('schema_version')}"
        )


def test_golden_files_correct_kinds():
    """Each service subdirectory has the expected Kind files."""
    for svc, expected_kinds in _EXPECTED_KINDS.items():
        svc_dir = _GOLDEN_DIR / svc
        actual_kinds = {p.stem for p in svc_dir.glob("*.json")}
        assert actual_kinds == expected_kinds, (
            f"{svc}: expected {expected_kinds}, got {actual_kinds}"
        )


# ---------------------------------------------------------------------------
# Fixture validation
# ---------------------------------------------------------------------------


_CRD_SERVICE_DIRS = {"cert-manager", "external-secrets", "traefik"}


def _crd_fixtures() -> list[Path]:
    """Return only CRD spec fixture JSON files (service sub-directories)."""
    return [
        p for p in _FIXTURES_DIR.rglob("*.json")
        if p.parent.name in _CRD_SERVICE_DIRS
    ]


def test_fixtures_exist():
    """fixtures directory contains fixture files for all 21 Kinds."""
    assert _FIXTURES_DIR.is_dir(), f"fixtures dir not found: {_FIXTURES_DIR}"
    all_json = _crd_fixtures()
    assert len(all_json) == 21, f"Expected 21 fixtures, found {len(all_json)}"


def test_fixture_required_keys():
    """Each fixture file has required keys."""
    required_keys = {
        "kind", "group", "version", "plural", "scope",
        "service", "spec_properties", "spec_required",
    }
    for json_path in sorted(_crd_fixtures()):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        missing = required_keys - set(data.keys())
        assert not missing, f"{json_path.name}: missing keys {missing}"
        # spec_properties should be a dict
        assert isinstance(data["spec_properties"], dict), (
            f"{json_path.name}: spec_properties should be dict"
        )
        # spec_required should be a list
        assert isinstance(data["spec_required"], list), (
            f"{json_path.name}: spec_required should be list"
        )


# ---------------------------------------------------------------------------
# assert_json_equivalent helper tests
# ---------------------------------------------------------------------------


def test_assert_json_equivalent_identical():
    """assert_json_equivalent detects identical dicts as equal."""
    d = {"a": 1, "b": [{"field": "x"}, {"field": "y"}]}
    assert_json_equivalent(d, d)


def test_assert_json_equivalent_reordered_keys():
    """assert_json_equivalent handles different key ordering."""
    d1 = {"b": 2, "a": 1}
    d2 = {"a": 1, "b": 2}
    assert_json_equivalent(d1, d2)


def test_assert_json_equivalent_reordered_arrays():
    """assert_json_equivalent handles array ordering (sorts by field key)."""
    d1 = {"items": [{"field": "b", "val": 2}, {"field": "a", "val": 1}]}
    d2 = {"items": [{"field": "a", "val": 1}, {"field": "b", "val": 2}]}
    assert_json_equivalent(d1, d2)


def test_assert_json_equivalent_different():
    """assert_json_equivalent detects different dicts as unequal."""
    d1 = {"a": 1}
    d2 = {"a": 2}
    with pytest.raises(AssertionError, match="JSON mismatch"):
        assert_json_equivalent(d1, d2)


def test_assert_json_equivalent_nested():
    """assert_json_equivalent handles nested structures."""
    d1 = {"outer": {"items": [{"field": "b"}, {"field": "a"}]}}
    d2 = {"outer": {"items": [{"field": "a"}, {"field": "b"}]}}
    assert_json_equivalent(d1, d2)


# ---------------------------------------------------------------------------
# conftest fixture smoke tests
# ---------------------------------------------------------------------------


def test_conftest_fixtures_load(cert_manager_fixtures, external_secrets_fixtures, traefik_fixtures):
    """conftest fixtures load without error."""
    assert len(cert_manager_fixtures) == 6
    assert len(external_secrets_fixtures) == 5
    assert len(traefik_fixtures) == 10


def test_all_fixtures_combined(all_fixtures):
    """all_fixtures combines all services."""
    assert len(all_fixtures) == 21
