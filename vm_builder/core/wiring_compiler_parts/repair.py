"""LLM repair loop for wiring playbooks that fail validation.

Captures failure text, asks an LLM to reclassify offending fields,
regenerates via the mechanical assembler, and re-validates.  Max 3 retries.
Uses dependency injection (llm_call_fn) so tests never hit a real API.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from vm_builder.core.wiring_compiler_parts.assembler import assemble_playbook
from vm_builder.core.wiring_compiler_parts.models import (
    ClassifiedField, FieldRole, WiringIR,
)
from vm_builder.core.wiring_compiler_parts.validator import validate_tier1

_REPAIR_PROMPT = """\
You previously classified fields for a wiring playbook that failed validation.

Error message:
{error_message}

The failing playbook was generated for:
  Consumer: {consumer_app}, Endpoint: {method} {endpoint}
  Provider: {provider_app}

Original classifications:
{original_classifications_json}

The OpenAPI spec for this endpoint shows:
{spec_excerpt}

Please re-classify the fields that caused the failure. Only include fields
that need to change.

Return ONLY valid JSON:
{{"reclassifications": [{{"field": "fieldName", "role": "...", "default_value": "...", "reason": "..."}}]}}"""


@dataclass
class RepairResult:
    """Result of a repair attempt."""
    success: bool
    playbook_content: str = ""
    ir: WiringIR | None = None
    attempts: int = 0
    repairs: list[dict] = field(default_factory=list)
    final_error: str = ""


def _build_repair_prompt(ir: WiringIR, error: str, spec_excerpt: str) -> str:
    return _REPAIR_PROMPT.format(
        error_message=error, consumer_app=ir.consumer_app,
        method=ir.method, endpoint=ir.endpoint, provider_app=ir.provider_app,
        original_classifications_json=json.dumps([f.to_dict() for f in ir.fields], indent=2),
        spec_excerpt=spec_excerpt or "(not available)")


def _parse_reclassifications(raw: str) -> list[dict[str, Any]]:
    try:
        items = json.loads(raw).get("reclassifications")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return []
    return [i for i in items if isinstance(i, dict) and "field" in i] if isinstance(items, list) else []


def _apply_reclassifications(ir: WiringIR, reclass: list[dict[str, Any]]) -> WiringIR:
    by_name, roles = {r["field"]: r for r in reclass}, {e.value: e for e in FieldRole}
    new_fields: list[ClassifiedField] = []
    for f in ir.fields:
        rc = by_name.get(f.name)
        if rc:
            new_fields.append(ClassifiedField(
                name=f.name, role=roles.get(rc.get("role", ""), f.role),
                value=rc.get("default_value", f.value),
                confidence=f.confidence, source=f.source, layer=f.layer))
        else:
            new_fields.append(f)
    return WiringIR(
        consumer_app=ir.consumer_app, provider_app=ir.provider_app,
        endpoint=ir.endpoint, method=ir.method, get_endpoint=ir.get_endpoint,
        status_endpoint=ir.status_endpoint, auth=ir.auth,
        idempotent_check=ir.idempotent_check, fields=new_fields,
        execution_mode=ir.execution_mode, provenance=ir.provenance,
        generated_at=ir.generated_at)


def attempt_repair(
    ir: WiringIR, failure: str, spec_excerpt: str = "",
    max_retries: int = 3, llm_call_fn: Callable[[str], str] | None = None,
) -> RepairResult:
    """Repair a failing playbook: prompt -> LLM reclassify -> reassemble -> validate."""
    if llm_call_fn is None:
        return RepairResult(success=False, final_error="No LLM call function provided")
    repairs: list[dict] = []
    current_ir, current_error = ir, failure
    for attempt in range(1, max_retries + 1):
        prompt = _build_repair_prompt(current_ir, current_error, spec_excerpt)
        reclass = _parse_reclassifications(llm_call_fn(prompt))
        if not reclass:
            repairs.append({"attempt": attempt, "repair": "no_reclassifications",
                            "error": current_error[:200]})
            continue
        current_ir = _apply_reclassifications(current_ir, reclass)
        playbook = assemble_playbook(current_ir)
        result = validate_tier1(playbook)
        for rc in reclass:
            repairs.append({"attempt": attempt,
                            "repair": f"field_reclassified:{rc['field']}:{rc.get('role', 'unknown')}",
                            "error": current_error[:200]})
        if result.valid:
            return RepairResult(success=True, playbook_content=playbook,
                                ir=current_ir, attempts=attempt, repairs=repairs)
        current_error = "; ".join(result.errors)
    return RepairResult(success=False, attempts=max_retries,
                        repairs=repairs, final_error=current_error)
