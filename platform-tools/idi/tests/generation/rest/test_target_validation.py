"""Tests for target existence validation — phantom target filtering."""
from __future__ import annotations

from idi.generation.dep_adapters.base import Dependency


def _dep(
    target_resource: str,
    target_operation: str = "create",
    target_service: str | None = None,
    field: str = "some_id",
    source: str = "generic_odg:body",
    confidence: float = 0.5,
    fact_ref: str | None = None,
    lineage_type: str = "copy",
    discriminator_value: str | None = None,
) -> Dependency:
    return Dependency(
        field=field,
        target_resource=target_resource,
        target_operation=target_operation,
        confidence=confidence,
        source=source,
        fact_ref=fact_ref,
        lineage_type=lineage_type,
        discriminator_value=discriminator_value,
        target_service=target_service,
    )


def _build_dep_path(
    d: Dependency, api_name: str,
) -> str:
    """Mirror the dep_path construction from cli.py."""
    return f"{d.target_service or api_name}/{d.target_resource}/{d.target_operation}"


def _validate_dep(d: Dependency, api_name: str, generated: dict) -> bool:
    """Mirror the validation logic from cli.py: cross-service bypasses check."""
    if d.target_service:
        return True  # Cross-service deps bypass validation
    dep_path = _build_dep_path(d, api_name)
    return dep_path in generated


class TestTargetValidation:
    """Phantom targets are filtered from depends_on using generated_skill_paths."""

    def test_dep_to_existing_skill_path_is_kept(self):
        generated = {"vault/secrets/create": {}}
        d = _dep("secrets")
        assert _validate_dep(d, "vault", generated)

    def test_dep_to_missing_skill_path_is_dropped(self):
        generated = {"vault/secrets/create": {}}
        d = _dep("csr")  # csr has no POST → no create skill
        assert not _validate_dep(d, "vault", generated)

    def test_cross_service_dep_bypasses_validation(self):
        # Cross-service deps are always kept even if not in generated paths
        generated = {}  # Empty — no cross-service paths available
        d = _dep("namespace", target_service="kubernetes")
        assert _validate_dep(d, "vault", generated)

    def test_cross_service_dep_constructs_path_correctly(self):
        d = _dep("namespace", target_service="kubernetes")
        path = _build_dep_path(d, "vault")
        assert path == "kubernetes/namespace/create"

    def test_phantom_targets_removed_from_depends_on(self):
        generated = {
            "vault/secrets/create": {},
            "vault/mounts/create": {},
        }
        deps = [
            _dep("secrets"),       # exists
            _dep("csr"),           # phantom
            _dep("mounts"),        # exists
            _dep("token-max-ttl"), # phantom
        ]
        result = [d for d in deps if _validate_dep(d, "vault", generated)]
        assert len(result) == 2
        assert result[0].target_resource == "secrets"
        assert result[1].target_resource == "mounts"

    def test_valid_dep_fields_preserved(self):
        generated = {"vault/secrets/create": {}}
        d = _dep(
            "secrets",
            field="secret_id",
            source="generic_odg:body",
            fact_ref="vault/secrets/create:id",
            lineage_type="copy",
            discriminator_value="kv",
        )
        assert _validate_dep(d, "vault", generated)
        assert d.field == "secret_id"
        assert d.source == "generic_odg:body"
        assert d.fact_ref == "vault/secrets/create:id"
        assert d.lineage_type == "copy"
        assert d.discriminator_value == "kv"

    def test_non_create_operation_validated(self):
        generated = {"vault/secrets/list": {}}
        d = _dep("secrets", target_operation="list")
        assert _validate_dep(d, "vault", generated)
        # But create is phantom
        d2 = _dep("secrets", target_operation="create")
        assert not _validate_dep(d2, "vault", generated)
