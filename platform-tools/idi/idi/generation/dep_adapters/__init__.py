"""Pluggable dependency detection adapters.

Usage:
    from idi.generation.dep_adapters import DepAdapterRegistry

    registry = DepAdapterRegistry()
    deps, outputs = registry.detect(operation_info, spec, known_resources)
"""

from idi.generation.dep_adapters.base import (
    DepAdapter,
    Dependency,
    DetectionSource,
    OperationInfo,
    Output,
)
from idi.generation.dep_adapters.registry import DepAdapterRegistry

__all__ = [
    "DepAdapter",
    "DepAdapterRegistry",
    "Dependency",
    "DetectionSource",
    "OperationInfo",
    "Output",
]
