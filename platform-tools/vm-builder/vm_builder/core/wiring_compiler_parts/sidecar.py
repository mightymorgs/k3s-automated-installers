"""Sidecar generation for .wiring-template.json and .wiring-exception.json files."""
from __future__ import annotations

from typing import Any

from vm_builder.core.wiring_compiler_parts.models import WiringException, WiringIR


def generate_sidecar(
    ir: WiringIR,
    repairs: list[dict] | None = None,
    molecule_status: str | None = None,
    molecule_tier: int | None = None,
) -> dict[str, Any]:
    """Generate a .wiring-template.json sidecar dict from a WiringIR.

    The sidecar includes all IR fields plus validation/repair tracking
    fields that will be populated by the runtime pipeline (Subplan 04).
    Runtime fields (molecule_status, molecule_tier) are omitted when unset
    so the sidecar validates against wiring-ir.schema.json.

    Args:
        ir: The wiring intermediate representation.
        repairs: List of repair attempt dicts from the LLM repair loop.
            Empty list means first-pass classification was correct.
        molecule_status: Molecule validation outcome (e.g. "passed", "failed").
        molecule_tier: Molecule validation tier that produced the status (1, 2, or 3).
    """
    sidecar = ir.to_dict()
    sidecar["repairs"] = repairs if repairs is not None else []
    if molecule_status is not None:
        sidecar["molecule_status"] = molecule_status
    if molecule_tier is not None:
        sidecar["molecule_tier"] = molecule_tier
    return sidecar


def generate_exception_sidecar(exception: WiringException) -> dict[str, Any]:
    """Generate a .wiring-exception.json sidecar dict."""
    return exception.to_dict()
