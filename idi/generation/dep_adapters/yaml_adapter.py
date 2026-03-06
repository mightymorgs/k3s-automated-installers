"""YAML-based dependency adapter loader (Layer 2).

Wraps declarative YAML files as ``DepAdapter`` instances.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output


class YamlDepAdapter:
    """Wraps a YAML adapter definition as a DepAdapter."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.name: str = config["name"]
        self.priority: int = config.get("priority", 70)
        self._matches: dict[str, Any] = config.get("matches", {})
        self._deps: list[dict] = config.get("dependencies", [])
        self._outputs: list[dict] = config.get("outputs", [])

    @classmethod
    def from_file(cls, path: Path) -> YamlDepAdapter:
        with open(path) as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError(f"Expected dict in {path}")
        return cls(config)

    def matches(self, spec: dict, service_name: str) -> bool:
        if title := self._matches.get("info_title_contains"):
            if title.lower() in spec.get("info", {}).get("title", "").lower():
                return True
        if sn := self._matches.get("service_name"):
            if service_name.lower() == sn.lower():
                return True
        if service_name.lower() == self.name.lower():
            return True
        return False

    def detect_dependencies(
        self, operation: OperationInfo, spec: dict, known_resources: set[str],
    ) -> list[Dependency]:
        results: list[Dependency] = []
        for decl in self._deps:
            if decl.get("source_resource") != operation.resource:
                continue
            if decl.get("source_operation", "create") != operation.operation:
                continue
            for target in decl.get("targets", []):
                results.append(Dependency(
                    field=decl["field"],
                    target_resource=target["resource"],
                    target_operation=target.get("operation", "create"),
                    fact_ref=f"facts://{operation.service}/{target['resource']}#id",
                    confidence=decl.get("confidence", 0.85),
                    source=f"yaml:{self.name}",
                    lineage_type=decl.get("lineage_type", "copy"),
                    discriminator_value=target.get("discriminator_value"),
                ))
        return results

    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]:
        results: list[Output] = []
        for decl in self._outputs:
            if decl.get("resource") != operation.resource:
                continue
            if decl.get("operation", "create") != operation.operation:
                continue
            for field in decl.get("fields", []):
                fact_field = field.get("fact_field", field["response_field"])
                results.append(Output(
                    field=field["response_field"],
                    fact_ref=f"facts://{operation.service}/{operation.resource}#{fact_field}",
                    source=f"yaml:{self.name}",
                ))
        return results
