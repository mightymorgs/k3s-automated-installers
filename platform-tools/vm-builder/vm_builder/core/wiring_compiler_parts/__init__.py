"""Wiring compiler — deterministic Phase 4 playbook generation from OpenAPI specs."""

from vm_builder.core.wiring_compiler_parts.assembler import assemble_playbook
from vm_builder.core.wiring_compiler_parts.sidecar import (
    generate_exception_sidecar,
    generate_sidecar,
)
from vm_builder.core.wiring_compiler_parts.models import (
    AuthStrategy,
    ClassifiedField,
    ExecutionMode,
    FieldRole,
    FieldSource,
    MatchSpec,
    StubTaxonomy,
    WiringException,
    WiringIR,
)

from vm_builder.core.wiring_compiler_parts.validator import (
    FailureClass,
    classify_failure,
    is_repairable,
)

__all__ = [
    "assemble_playbook",
    "generate_exception_sidecar",
    "generate_sidecar",
    "AuthStrategy",
    "ClassifiedField",
    "ExecutionMode",
    "FailureClass",
    "FieldRole",
    "FieldSource",
    "MatchSpec",
    "StubTaxonomy",
    "WiringException",
    "WiringIR",
    "classify_failure",
    "is_repairable",
]
