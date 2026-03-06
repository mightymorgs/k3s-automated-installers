"""Schema validation for skill JSON files.

Provides three validation functions — one for each skill schema:

- ``validate_manifest()`` — resource-level manifest.json
- ``validate_operation()`` — per-operation JSON (create.json, list.json, etc.)
- ``validate_field()`` — per-field JSON (name.json, authorization_flow.json, etc.)

Each function loads its corresponding JSON Schema from
``schemas/skill/`` and delegates to ``jsonschema.validate()``.
A ``jsonschema.ValidationError`` is raised on invalid data.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import validate, ValidationError  # noqa: F401 — re-exported for callers

SCHEMA_ROOT = Path(__file__).resolve().parent.parent.parent / "schemas" / "skill"


@lru_cache(maxsize=4)
def _load_schema(name: str) -> dict:
    """Load and cache a JSON Schema by filename.

    Args:
        name: Schema filename (e.g. ``"manifest.schema.json"``).

    Returns:
        Parsed JSON Schema as a dict.
    """
    path = SCHEMA_ROOT / name
    return json.loads(path.read_text())


def validate_manifest(data: dict) -> None:
    """Validate a manifest.json dict against the skill manifest schema.

    Args:
        data: Parsed manifest JSON.

    Raises:
        jsonschema.ValidationError: If *data* does not conform to the schema.
    """
    validate(instance=data, schema=_load_schema("manifest.schema.json"))


def validate_operation(data: dict) -> None:
    """Validate an operation JSON dict against the skill operation schema.

    Args:
        data: Parsed operation JSON (e.g. create.json, list.json).

    Raises:
        jsonschema.ValidationError: If *data* does not conform to the schema.
    """
    validate(instance=data, schema=_load_schema("operation.schema.json"))


def validate_field(data: dict) -> None:
    """Validate a field JSON dict against the skill field schema.

    Args:
        data: Parsed field JSON (e.g. name.json, authorization_flow.json).

    Raises:
        jsonschema.ValidationError: If *data* does not conform to the schema.
    """
    validate(instance=data, schema=_load_schema("field.schema.json"))
