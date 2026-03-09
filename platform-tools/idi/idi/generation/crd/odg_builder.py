"""CRD Operation Dependency Graph — producer-consumer matching.

Adapts RESTler's approach: collect all output_declarations (producers) and
input_refs (consumers), match by target_kind + target_group, build DEPENDS_ON
and PRODUCES edges for the Neo4j graph.
"""
from __future__ import annotations

from dataclasses import dataclass

from idi.generation.crd.field_classifier import ClassifiedField


@dataclass
class CrdDependency:
    """A dependency edge between two CRD Kinds."""

    source_kind: str
    source_group: str
    target_kind: str
    target_group: str
    field: str
    fact_ref: str
    confidence: float
    role: str  # input_ref or output_declaration


@dataclass
class CrdProduces:
    """A PRODUCES edge from a CRD Kind to a Fact."""

    source_kind: str
    source_group: str
    fact_uri: str
    field: str
    produces_kind: str
    produces_group: str


def build_odg(
    kinds: dict[str, list[ClassifiedField]],
    service: str,
    group: str,
) -> list[CrdDependency]:
    """Build the Operation Dependency Graph for CRD Kinds.

    Args:
        kinds: Map of Kind name -> classified fields.
        service: Service name.
        group: Default API group.

    Returns:
        List of CrdDependency edges.
    """
    deps: list[CrdDependency] = []

    for kind_name, fields in kinds.items():
        for f in fields:
            if f.role != "input_ref" or not f.target_kind:
                continue

            # Skip self-references.
            if f.target_kind == kind_name and (f.target_group or group) == group:
                continue

            target_group = f.target_group or group
            fact_ref = f"crdfacts://{target_group}/{f.target_kind}#name"

            deps.append(CrdDependency(
                source_kind=kind_name,
                source_group=group,
                target_kind=f.target_kind,
                target_group=target_group,
                field=f.field,
                fact_ref=fact_ref,
                confidence=f.confidence,
                role="input_ref",
            ))

    return deps


def build_produces(
    kinds: dict[str, list[ClassifiedField]],
    service: str,
    group: str,
) -> list[CrdProduces]:
    """Build PRODUCES edges from output_declarations.

    Returns:
        List of CrdProduces edges.
    """
    produces: list[CrdProduces] = []

    for kind_name, fields in kinds.items():
        for f in fields:
            if f.role != "output_declaration":
                continue

            target_group = f.target_group or "core"
            target_kind = f.target_kind or "Unknown"
            fact_uri = f"crdfacts://{target_group}/{target_kind}#name"

            produces.append(CrdProduces(
                source_kind=kind_name,
                source_group=group,
                fact_uri=fact_uri,
                field=f.field,
                produces_kind=target_kind,
                produces_group=target_group,
            ))

    return produces
