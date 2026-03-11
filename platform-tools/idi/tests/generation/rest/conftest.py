"""Shared fixtures for REST pipeline improvement tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[5]  # k3s-automated-installers/
CATALOG_SPECS = REPO_ROOT / "catalog" / "specs"


def _load_spec_if_exists(filename: str) -> dict[str, Any] | None:
    """Load a JSON spec from catalog/specs/ if it exists, else return None."""
    path = CATALOG_SPECS / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Benchmark spec fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault_spec():
    """Load Vault OpenAPI spec. Skips test if spec file is missing."""
    spec = _load_spec_if_exists("vault-openapi.json")
    if spec is None:
        pytest.skip("vault-openapi.json not found in catalog/specs/")
    return spec


@pytest.fixture
def authentik_spec():
    """Load Authentik OpenAPI spec. Skips test if spec file is missing."""
    spec = _load_spec_if_exists("authentik-openapi.json")
    if spec is None:
        pytest.skip("authentik-openapi.json not found in catalog/specs/")
    return spec


@pytest.fixture
def sonarr_spec():
    """Load Sonarr OpenAPI spec. Skips test if spec file is missing."""
    spec = _load_spec_if_exists("sonarr-openapi.json")
    if spec is None:
        pytest.skip("sonarr-openapi.json not found in catalog/specs/")
    return spec


# ---------------------------------------------------------------------------
# Synthetic schema fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_openapi_spec() -> dict[str, Any]:
    """Valid OAS 3.0 spec with 2 operations for basic pipeline testing."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "email": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                    "responses": {
                        "201": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "/users/{user_id}": {
                "get": {
                    "operationId": "getUser",
                    "parameters": [
                        {"name": "user_id", "in": "path", "required": True,
                         "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


@pytest.fixture
def known_resources():
    """Set of resource names for FK matching in tests."""
    return {"users", "organizations", "teams", "projects", "roles"}
