"""Markdown rendering for VM Builder repo skills."""

from __future__ import annotations

from typing import Any


def render_skill_markdown(
    operation: dict[str, Any],
    service: str = "vm-builder",
) -> str:
    """Render one operation to skill markdown with YAML frontmatter."""
    resource = str(operation["resource"])
    op_name = str(operation["operation"])
    skill_name = f"{service}/{resource}/{op_name}"

    source_rel = str(operation.get("source_file", ""))
    if "vm_builder/" in source_rel:
        source_rel = source_rel[source_rel.index("vm_builder/") :]

    depends_on = list(operation.get("depends_on", []))

    depends_lines = ""
    if depends_on:
        depends_lines = "depends_on:\n"
        for dep in depends_on:
            depends_lines += f"  - {dep}\n"

    docstring = str(operation.get("docstring", "")) or f"{op_name} operation on {resource}"
    signature = str(operation.get("signature", ""))

    # Escape inner quotes so YAML frontmatter remains valid.
    description = docstring.split("\n")[0].replace('"', '\\"')

    if depends_on:
        dependency_lines = "\n".join(f"- `{dep}`" for dep in depends_on)
    else:
        dependency_lines = "None"

    return f"""---
name: {skill_name}
description: "{description}"
service: {service}
resource: {resource}
operation: {op_name}
layer: repo
source_file: {source_rel}
source_function: {operation["name"]}
{depends_lines}max_tokens: 500
---

## What It Does

{docstring}

## Function Signature

```python
{signature}
```

## Key Logic

<!-- Review and fill in key implementation details -->

## Dependencies

{dependency_lines}
"""

