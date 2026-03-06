"""Config lifecycle models for per-app _config and _overrides."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field


class ConfigUpdateRequest(BaseModel):
    """Request to update a single config field for an app."""

    field: str
    value: str | int | bool | dict | list


def _infer_field_type(value: Any) -> str:
    """Infer a simple JSON Schema type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


class AppConfigResponse(BaseModel):
    """Full config state for an app on a VM.

    Accepts flat ``config/overrides/defaults`` from the backend and
    exposes a ``fields`` dict keyed by field name for the frontend
    ``ConfigEditor`` component.
    """

    app_id: str
    config: dict[str, Any] = Field(exclude=True)
    overrides: list[str] = Field(exclude=True)
    defaults: dict[str, Any] = Field(exclude=True)

    @computed_field  # type: ignore[misc]
    @property
    def fields(self) -> dict[str, dict[str, Any]]:
        all_keys = sorted(set(self.config) | set(self.defaults))
        result: dict[str, dict[str, Any]] = {}
        for key in all_keys:
            value = self.config.get(key)
            default = self.defaults.get(key)
            sample = value if value is not None else default
            result[key] = {
                "value": value,
                "default": default,
                "field_def": {"type": _infer_field_type(sample)},
                "is_override": key in self.overrides,
            }
        return result
