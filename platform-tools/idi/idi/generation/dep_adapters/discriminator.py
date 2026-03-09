"""Structural adapter: OpenAPI discriminator keyword detection.

Priority: 90 (structural proof from the spec).
"""
from __future__ import annotations

import re
from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output


class DiscriminatorAdapter:
    name = "discriminator"
    priority = 90

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        return _has_discriminator(spec)

    def detect_dependencies(
        self, operation: OperationInfo, spec: dict, known_resources: set[str],
    ) -> list[Dependency]:
        body = operation.body_schema
        if not body or "properties" not in body:
            return []
        results: list[Dependency] = []
        for field_name, field_schema in body.get("properties", {}).items():
            disc = field_schema.get("discriminator")
            if not disc or "mapping" not in disc:
                continue
            for disc_value, schema_ref in disc["mapping"].items():
                target = _ref_to_resource(schema_ref) or disc_value
                results.append(Dependency(
                    field=field_name, target_resource=target,
                    fact_ref=f"facts://{operation.service}/{target}#id",
                    confidence=0.95, source="discriminator",
                    discriminator_value=disc_value,
                ))
        return results

    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]:
        return []


def _has_discriminator(obj: Any, depth: int = 12) -> bool:
    """Recursively check whether an OpenAPI spec contains a discriminator with a mapping."""
    if depth <= 0 or not isinstance(obj, dict):
        return False
    if "discriminator" in obj and isinstance(obj["discriminator"], dict) and "mapping" in obj["discriminator"]:
        return True
    for v in obj.values():
        if isinstance(v, dict) and _has_discriminator(v, depth - 1):
            return True
        if isinstance(v, list):
            for item in v:
                if _has_discriminator(item, depth - 1):
                    return True
    return False


def _ref_to_resource(ref: str) -> str | None:
    """Convert a $ref string like '#/components/schemas/OAuth2Provider' to 'o-auth2'."""
    if not ref:
        return None
    name = ref.rsplit("/", 1)[-1]
    for suffix in ("Provider", "Schema", "Model", "Request", "Response", "Config"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[:-len(suffix)]
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name).lower()
