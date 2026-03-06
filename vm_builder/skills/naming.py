"""Naming utilities for VM Builder skill generation."""

from __future__ import annotations

import re
from typing import Any

# Insert hyphens before uppercase letters preceded by lowercase/digits.
_PASCAL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])([A-Z])")


def to_kebab(name: str) -> str:
    """Convert snake_case or PascalCase names to kebab-case."""
    with_hyphens = _PASCAL_BOUNDARY_RE.sub(r"-\1", name)
    return with_hyphens.replace("_", "-").lower()


def skill_filename(
    operation: dict[str, Any],
    colliding_operations: set[str],
) -> str:
    """Build a collision-safe skill filename for an operation.

    Args:
        operation: Operation metadata dict.
        colliding_operations: Operation names that appear multiple times in
            the same module/resource and require class-name prefixes.

    Returns:
        Filename like ``create-vm.md`` or
        ``app-install-result-runner-label.md``.
    """
    op_name = str(operation["operation"])
    class_name = operation.get("class_name")

    if op_name in colliding_operations and class_name:
        prefix = f"{to_kebab(str(class_name))}-"
    else:
        prefix = ""

    return f"{prefix}{op_name}.md"

