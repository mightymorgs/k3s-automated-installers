"""Tier 1 and Tier 2 validation for wiring-compiler-generated playbooks.

Tier 1: YAML syntax, Jinja2 template balance, play structure,
metadata presence, and task naming.  Pure-Python -- no Ansible required.
Tier 2: ansible-playbook --syntax-check on the generated file.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

_UNCLOSED = re.compile(r"\{\{(?!.*\}\})")


@dataclass
class ValidationResult:
    """Result of playbook validation."""
    valid: bool
    tier: int  # 1 or 2
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_play(d: object) -> bool:
    return isinstance(d, dict) and "hosts" in d and "tasks" in d


def validate_tier1(content: str) -> ValidationResult:
    """Tier 1: YAML syntax and structural checks.

    Errors make valid=False; warnings are advisory only.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not content or not content.strip():
        return ValidationResult(valid=False, tier=1, errors=["Empty playbook content"])

    # 1. Unbalanced Jinja2 braces (before YAML parse)
    for lineno, line in enumerate(content.splitlines(), 1):
        if _UNCLOSED.search(line.split("#")[0]):
            errors.append(f"Unbalanced Jinja2 braces on line {lineno}")
    if errors:
        return ValidationResult(valid=False, tier=1, errors=errors)

    # 2. YAML syntax
    try:
        docs = list(yaml.safe_load_all(content))
    except yaml.YAMLError as exc:
        return ValidationResult(valid=False, tier=1, errors=[f"YAML parse error: {exc}"])

    plays = [d for d in docs if d is not None]

    # 3. At least one play with hosts + tasks
    if not plays:
        errors.append("No YAML documents found")
    elif not any(_is_play(p) for p in plays):
        # Accept list-of-plays (yaml.safe_load wraps single doc in list)
        if not any(_is_play(i) for p in plays if isinstance(p, list) for i in p):
            errors.append("No play with 'hosts' and 'tasks' keys found")

    # 4. Task names
    for p in plays:
        for item in (p if isinstance(p, list) else [p]):
            if isinstance(item, dict):
                for t in item.get("tasks") or []:
                    if isinstance(t, dict) and "name" not in t:
                        warnings.append("Task without 'name' key detected")

    # 5. Metadata comment
    if "# playbook_metadata:" not in content:
        warnings.append("Missing '# playbook_metadata:' comment block")
    elif "requires_apps" not in content:
        warnings.append("Metadata missing 'requires_apps' field")

    return ValidationResult(valid=not errors, tier=1, errors=errors, warnings=warnings)


def validate_tier2(playbook_path: Path) -> ValidationResult:
    """Tier 2 validation: ansible-playbook --syntax-check.

    Runs ``ansible-playbook --syntax-check`` on the generated playbook file.
    Catches undefined variables, invalid module references, structural errors.

    Args:
        playbook_path: Path to the playbook YAML file on disk.

    Returns:
        ValidationResult with tier=2.
    """
    if not shutil.which("ansible-playbook"):
        return ValidationResult(
            valid=False, tier=2, errors=["ansible-playbook not found"],
        )
    proc = subprocess.run(
        ["ansible-playbook", "--syntax-check", str(playbook_path)],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return ValidationResult(valid=True, tier=2)
    stderr = proc.stderr.strip() or proc.stdout.strip()
    return ValidationResult(valid=False, tier=2, errors=[stderr])


class FailureClass(str, Enum):
    """Classification of validation failures."""

    SCHEMA_FAILURE = "schema_failure"
    BINDING_FAILURE = "binding_failure"
    ASSEMBLER_FAILURE = "assembler_failure"
    ENVIRONMENT_FAILURE = "environment_failure"
    NETWORK_FAILURE = "network_failure"
    SEMANTIC_RUNTIME_FAILURE = "semantic_runtime_failure"


_FAILURE_PATTERNS: list[tuple[list[str], FailureClass]] = [
    (["yaml", "parse", "scan", "syntax"], FailureClass.SCHEMA_FAILURE),
    (["undefined", "undeclared", "not defined", "variable"], FailureClass.BINDING_FAILURE),
    (["not found", "not installed", "command not found", "no such file"], FailureClass.ENVIRONMENT_FAILURE),
    (["tasks", "play", "hosts", "missing"], FailureClass.ASSEMBLER_FAILURE),
    (["connection", "timeout", "refused", "unreachable"], FailureClass.NETWORK_FAILURE),
    (["status", "response", "unexpected"], FailureClass.SEMANTIC_RUNTIME_FAILURE),
]


def classify_failure(error: str) -> FailureClass:
    """Classify a validation error message into a failure category.

    Only repairable classes (SCHEMA_FAILURE, BINDING_FAILURE) may flow to LLM repair.

    Args:
        error: Error message from validation.

    Returns:
        Classified failure type.
    """
    lower = error.lower()
    for keywords, cls in _FAILURE_PATTERNS:
        if any(kw in lower for kw in keywords):
            return cls
    return FailureClass.ASSEMBLER_FAILURE


def is_repairable(failure_class: FailureClass) -> bool:
    """Check if a failure class is eligible for LLM repair."""
    return failure_class in (FailureClass.SCHEMA_FAILURE, FailureClass.BINDING_FAILURE)
