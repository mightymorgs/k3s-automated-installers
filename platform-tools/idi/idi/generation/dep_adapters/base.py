"""Base protocol and data types for dependency adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class DetectionSource(str, Enum):
    """Algorithm identifier for each edge the pipeline emits."""

    DEFAULT = "rest:default"
    CREDENTIAL_REGEX = "rest:credential_regex"
    READONLY_FIELD = "rest:readonly_field"
    WRITEONLY_FIELD = "rest:writeonly_field"
    FK_SUFFIX = "rest:fk_suffix"
    SCHEMA_NORMALIZE = "rest:schema_normalize"
    PRODUCER_VALIDITY = "rest:producer_validity"
    ID_SYNONYM = "rest:id_synonym"
    OPENAPI_LINK = "rest:openapi_link"
    ENVELOPE_UNWRAP = "rest:envelope_unwrap"
    NESTED_PRODUCER = "rest:nested_producer"
    RESPONSE_WALK = "rest:response_walk"
    READONLY_DIFF = "rest:readonly_diff"
    NESTED_FK = "rest:nested_fk"
    ANNOTATION = "rest:annotation"


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
    path_param_schemas: dict[str, dict] = field(default_factory=dict)


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
    detection_source: DetectionSource = DetectionSource.DEFAULT


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
