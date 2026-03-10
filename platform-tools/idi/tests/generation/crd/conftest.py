"""Shared pytest fixtures for CRD pipeline tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_GOLDEN_DIR = Path(__file__).parent / "golden_files"

_SERVICES = ["cert-manager", "external-secrets", "traefik"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_json_dir(directory: Path) -> list[dict[str, Any]]:
    """Load all JSON files in a directory."""
    results = []
    if not directory.exists():
        return results
    for p in sorted(directory.glob("*.json")):
        results.append(json.loads(p.read_text(encoding="utf-8")))
    return results


def _sort_arrays(obj: Any) -> Any:
    """Recursively sort arrays in a JSON-like structure for comparison.

    Arrays of dicts are sorted by 'field_path' or 'field' key if present.
    """
    if isinstance(obj, dict):
        return {k: _sort_arrays(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        sorted_items = [_sort_arrays(item) for item in obj]
        if sorted_items and isinstance(sorted_items[0], dict):
            # Sort by field_path or field key if present.
            for sort_key in ("field_path", "field"):
                if sort_key in sorted_items[0]:
                    return sorted(sorted_items, key=lambda x: x.get(sort_key, ""))
        return sorted_items
    return obj


def assert_json_equivalent(actual: dict, expected: dict) -> None:
    """Compare two JSON dicts with canonical ordering.

    Sorts arrays by 'field' or 'field_path' key if present.
    Sorts dict keys. Raises AssertionError with diff on mismatch.
    """
    actual_sorted = _sort_arrays(actual)
    expected_sorted = _sort_arrays(expected)
    if actual_sorted != expected_sorted:
        # Build a useful diff message.
        import difflib
        actual_lines = json.dumps(actual_sorted, indent=2).splitlines(keepends=True)
        expected_lines = json.dumps(expected_sorted, indent=2).splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            expected_lines, actual_lines,
            fromfile="expected", tofile="actual",
        ))
        raise AssertionError(f"JSON mismatch:\n{diff}")


# ---------------------------------------------------------------------------
# Legacy monolithic builder (kept for Phase 1a golden-file regression tests)
# ---------------------------------------------------------------------------


def _legacy_fact_ref(field) -> str:
    """Build a crdfacts:// URI in the monolithic (v1.0) format."""
    group = field.target_group or "core"
    kind = field.target_kind or "Unknown"
    leaf = field.field.rsplit(".", 1)[-1]
    return f"crdfacts://{group}/{kind}#{leaf}"


def build_crd_skill_json_legacy(
    crd_info: dict[str, Any],
    fields,
    status_conditions: list[str] | None = None,
) -> dict[str, Any]:
    """Build a monolithic CRD skill JSON (schema v1.0) for golden-file testing.

    This is a copy of the original build_crd_skill_json, preserved for
    behavioral equivalence tests. Not used in production.
    """
    input_refs = []
    output_declarations = []
    config_fields = []

    for f in fields:
        if f.role == "input_ref" and f.target_kind:
            input_refs.append({
                "field": f.field,
                "target_kind": f.target_kind,
                "target_group": f.target_group or crd_info["group"],
                "role": "input_ref",
                "required": f.required,
                "cross_namespace": f.cross_namespace,
                "fact_ref": _legacy_fact_ref(f),
            })
        elif f.role == "output_declaration":
            output_declarations.append({
                "field": f.field,
                "produces_kind": f.target_kind or "Unknown",
                "produces_group": f.target_group or "core",
                "role": "output_declaration",
                "fact_ref": _legacy_fact_ref(f),
            })
        elif f.role == "config_field":
            entry: dict[str, Any] = {
                "field": f.field,
                "type": f.field_type,
            }
            if f.description:
                entry["description"] = f.description
            config_fields.append(entry)

    return {
        "schema_version": "1.0",
        "kind": crd_info["kind"],
        "group": crd_info["group"],
        "version": crd_info["version"],
        "plural": crd_info["plural"],
        "scope": crd_info["scope"],
        "service": crd_info["service"],
        "description": crd_info.get("description") or f"{crd_info['kind']} CRD",
        "input_refs": input_refs,
        "output_declarations": output_declarations,
        "config_fields": config_fields,
        "status_conditions": status_conditions or ["Ready"],
        "execution": {
            "method": "kubectl_apply",
            "wait_condition": "condition=Ready",
        },
    }


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


@pytest.fixture
def cert_manager_fixtures() -> list[dict[str, Any]]:
    """Load all cert-manager fixture files as a list of dicts."""
    return _load_json_dir(_FIXTURES_DIR / "cert-manager")


@pytest.fixture
def external_secrets_fixtures() -> list[dict[str, Any]]:
    """Load all external-secrets fixture files as a list of dicts."""
    return _load_json_dir(_FIXTURES_DIR / "external-secrets")


@pytest.fixture
def traefik_fixtures() -> list[dict[str, Any]]:
    """Load all traefik fixture files as a list of dicts."""
    return _load_json_dir(_FIXTURES_DIR / "traefik")


@pytest.fixture
def all_fixtures(
    cert_manager_fixtures: list[dict[str, Any]],
    external_secrets_fixtures: list[dict[str, Any]],
    traefik_fixtures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """All fixture files combined."""
    return cert_manager_fixtures + external_secrets_fixtures + traefik_fixtures


@pytest.fixture
def golden_file_path() -> Path:
    """Path to the golden_files directory."""
    return _GOLDEN_DIR


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """Temporary directory for output writer tests."""
    return tmp_path / "output"


# ---------------------------------------------------------------------------
# KindRegistry fixtures (fully wired in section-02)
# ---------------------------------------------------------------------------


@pytest.fixture
def core_only_registry():
    """KindRegistry with only the 18 core K8s resources (no CRDs registered)."""
    from idi.generation.crd.kind_registry import KindRegistry
    return KindRegistry()


@pytest.fixture
def populated_registry(core_only_registry, all_fixtures):
    """KindRegistry with 18 core + all 21 test CRDs registered."""
    for fix in all_fixtures:
        core_only_registry.register(
            kind=fix["kind"],
            plural=fix["plural"],
            group=fix["group"],
        )
    return core_only_registry
