"""Generic ODG heuristic adapter (Layer 1).

Thin facade that wires ``body_fk``, ``path_deps``, and
``output_detection`` together behind the ``DepAdapter`` protocol.

Priority: 50 (lowest -- structural and YAML adapters override).
"""
from __future__ import annotations

from typing import Any

from idi.generation.dep_adapters.base import Dependency, OperationInfo, Output
from idi.generation.dep_adapters.body_fk import detect_body_deps
from idi.generation.dep_adapters.output_detection import detect_outputs as _detect_outputs
from idi.generation.dep_adapters.path_deps import detect_path_deps
from idi.generation.dep_adapters.query_fk import detect_query_deps


class GenericODGAdapter:
    """Always-on heuristic FK detection adapter."""

    name = "generic_odg"
    priority = 50

    def matches(self, spec: dict[str, Any], service_name: str) -> bool:
        return True

    def detect_dependencies(
        self, operation: OperationInfo, spec: dict, known_resources: set[str],
    ) -> list[Dependency]:
        results: list[Dependency] = []
        # RESTler extracts consumers from ALL operations, not just writes.
        # The confidence system handles non-write operations appropriately.
        results.extend(detect_body_deps(operation, known_resources))
        results.extend(detect_path_deps(operation, known_resources))
        results.extend(detect_query_deps(operation, known_resources))
        return results

    def detect_outputs(self, operation: OperationInfo, spec: dict) -> list[Output]:
        return _detect_outputs(operation)
