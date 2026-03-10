"""Base protocol and data types for dependency adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OperationInfo:
    """Context for a single API operation passed to each adapter."""

    service: str
    resource: str
    operation: str
    path: str
    method: str
    body_schema: dict
    response_schema: dict
    path_params: list[str] = field(default_factory=list)
    query_params: list[dict] = field(default_factory=list)


@dataclass
class Dependency:
    """A detected FK dependency."""

    field: str
    target_resource: str
    target_operation: str = "create"
    fact_ref: str | None = None
    confidence: float = 0.5
    source: str = "unknown"
    lineage_type: str = "copy"
    discriminator_value: str | None = None
    target_service: str | None = None  # Set for cross-service deps (e.g. k8s)
    satisfaction: str = ""  # "required_value" or "optional_with_default"


@dataclass
class Output:
    """A detected output (produced fact)."""

    field: str
    fact_ref: str
    source: str = "unknown"
    priority: int = 1  # POST=3, PUT-create=2, PATCH=1


@runtime_checkable
class DepAdapter(Protocol):
    """Protocol for dependency detection adapters."""

    name: str
    priority: int

    def matches(self, spec: dict, service_name: str) -> bool: ...

    def detect_dependencies(
        self,
        operation: OperationInfo,
        spec: dict,
        known_resources: set[str],
    ) -> list[Dependency]: ...

    def detect_outputs(
        self,
        operation: OperationInfo,
        spec: dict,
    ) -> list[Output]: ...
