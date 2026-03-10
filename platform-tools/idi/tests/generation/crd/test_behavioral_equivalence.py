"""Phase 1a gate: behavioral equivalence for all 21 CRD skills.

Validates that the KindRegistry-based pipeline produces IDENTICAL monolithic
JSON output to the pre-refactor golden-file snapshots. This is the Phase 1a
acceptance gate -- no Phase 1b work should proceed until all tests pass.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.crd.field_classifier import classify_fields
from idi.generation.crd.output_writer import build_crd_skill_json
from tests.generation.crd.conftest import (
    _FIXTURES_DIR,
    _GOLDEN_DIR,
    assert_json_equivalent,
)


_ALL_KINDS = [
    ("cert-manager", "Certificate"),
    ("cert-manager", "CertificateRequest"),
    ("cert-manager", "Issuer"),
    ("cert-manager", "ClusterIssuer"),
    ("cert-manager", "Order"),
    ("cert-manager", "Challenge"),
    ("external-secrets", "ExternalSecret"),
    ("external-secrets", "SecretStore"),
    ("external-secrets", "ClusterSecretStore"),
    ("external-secrets", "ClusterExternalSecret"),
    ("external-secrets", "PushSecret"),
    ("traefik", "IngressRoute"),
    ("traefik", "IngressRouteTCP"),
    ("traefik", "IngressRouteUDP"),
    ("traefik", "Middleware"),
    ("traefik", "MiddlewareTCP"),
    ("traefik", "ServersTransport"),
    ("traefik", "ServersTransportTCP"),
    ("traefik", "TLSOption"),
    ("traefik", "TLSStore"),
    ("traefik", "TraefikService"),
]


def _load_fixture(service: str, kind: str) -> dict[str, Any]:
    path = _FIXTURES_DIR / service / f"{kind}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_golden(service: str, kind: str) -> dict[str, Any]:
    path = _GOLDEN_DIR / service / f"{kind}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestBehavioralEquivalence:
    """Full-pipeline golden-file comparison for all 21 CRD Kinds."""

    @pytest.mark.parametrize("service,kind_name", _ALL_KINDS)
    def test_full_pipeline_golden_match(self, populated_registry, service, kind_name):
        """classify_fields + build_crd_skill_json matches golden file for {kind_name}."""
        # 1. Load fixture.
        fixture = _load_fixture(service, kind_name)

        # 2. Classify fields with populated registry.
        fields = classify_fields(
            spec_properties=fixture["spec_properties"],
            spec_required=fixture["spec_required"],
            group=fixture["group"],
            kind=fixture["kind"],
            registry=populated_registry,
        )

        # 3. Build monolithic skill JSON.
        actual = build_crd_skill_json(
            crd_info=fixture,
            fields=fields,
        )

        # 4. Load golden file.
        expected = _load_golden(service, kind_name)

        # 5. Compare semantically.
        assert_json_equivalent(actual, expected)


class TestGoldenFileCoverage:
    """Verify fixture and golden file completeness."""

    def test_exactly_21_golden_files(self):
        all_json = list(_GOLDEN_DIR.rglob("*.json"))
        assert len(all_json) == 21

    def test_exactly_21_fixture_files(self):
        all_json = list(_FIXTURES_DIR.rglob("*.json"))
        assert len(all_json) == 21

    def test_all_kinds_have_golden_files(self):
        for service, kind in _ALL_KINDS:
            path = _GOLDEN_DIR / service / f"{kind}.json"
            assert path.exists(), f"Missing golden file: {path}"

    def test_all_kinds_have_fixtures(self):
        for service, kind in _ALL_KINDS:
            path = _FIXTURES_DIR / service / f"{kind}.json"
            assert path.exists(), f"Missing fixture: {path}"
