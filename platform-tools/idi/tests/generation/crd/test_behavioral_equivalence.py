"""Phase 2 behavioral SUPERSET gate for all 21 CRD skills.

Validates that the Phase 2 pipeline (schema_walker + ref_detector) produces
a SUPERSET of the Phase 1 golden-file refs. Phase 2 intentionally finds MORE
refs than Phase 1 (depth traversal, array handling) so exact equivalence is
no longer the test — we verify no regressions (all golden refs still present).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from idi.generation.crd.field_classifier import classify_fields
from tests.generation.crd.conftest import (
    _FIXTURES_DIR,
    _GOLDEN_DIR,
    build_crd_skill_json_legacy,
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


class TestBehavioralSuperset:
    """Phase 2 pipeline produces a SUPERSET of Phase 1 golden refs."""

    @pytest.mark.parametrize("service,kind_name", _ALL_KINDS)
    def test_all_golden_refs_present(self, populated_registry, service, kind_name):
        """Every Phase 1 golden input_ref is still found (no regressions)."""
        fixture = _load_fixture(service, kind_name)
        golden = _load_golden(service, kind_name)

        fields = classify_fields(
            spec_properties=fixture["spec_properties"],
            spec_required=fixture["spec_required"],
            group=fixture["group"],
            kind=fixture["kind"],
            registry=populated_registry,
        )

        actual = build_crd_skill_json_legacy(crd_info=fixture, fields=fields)

        # Build lookup sets for actual output.
        actual_ref_set = {
            (r["field"], r["target_kind"])
            for r in actual.get("input_refs", [])
        }
        actual_output_set = {
            (o["field"], o["produces_kind"])
            for o in actual.get("output_declarations", [])
        }

        # Verify every golden ref is present.
        for gref in golden.get("input_refs", []):
            key = (gref["field"], gref["target_kind"])
            assert key in actual_ref_set, (
                f"Missing golden input_ref: {key[0]} -> {key[1]} in {service}/{kind_name}"
            )

        # Verify every golden output is present.
        for gout in golden.get("output_declarations", []):
            key = (gout["field"], gout["produces_kind"])
            assert key in actual_output_set, (
                f"Missing golden output: {key[0]} -> {key[1]} in {service}/{kind_name}"
            )

    @pytest.mark.parametrize("service,kind_name", _ALL_KINDS)
    def test_no_spurious_refs_on_previously_correct_crds(self, populated_registry, service, kind_name):
        """All fields classified as input_ref have non-None target_kind (no unresolved refs)."""
        fixture = _load_fixture(service, kind_name)

        fields = classify_fields(
            spec_properties=fixture["spec_properties"],
            spec_required=fixture["spec_required"],
            group=fixture["group"],
            kind=fixture["kind"],
            registry=populated_registry,
        )

        for f in fields:
            if f.role == "input_ref":
                assert f.target_kind is not None, (
                    f"Unresolved input_ref: {f.field} in {service}/{kind_name} "
                    f"(detection_source={f.detection_source})"
                )


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
