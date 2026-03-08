"""VM name parsing and component validation."""

from __future__ import annotations

from typing import Dict, List, Tuple


def parse_vm_name(vm_name: str) -> Tuple[bool, Dict[str, str], List[str]]:
    """Parse and validate 7-component VM name."""
    parts = vm_name.split("-")
    if len(parts) != 7:
        return (
            False,
            {},
            [
                "VM name must have exactly 7 hyphen-delimited components, "
                f"got {len(parts)}"
            ],
        )

    components = {
        "client": parts[0],
        "vmtype": parts[1],
        "subtype": parts[2],
        "state": parts[3],
        "purpose": parts[4],
        "platform": parts[5],
        "version": parts[6],
    }

    errors: List[str] = []
    for key, value in components.items():
        if not value:
            errors.append(f"Component '{key}' cannot be empty")
        if not value.replace("_", "").replace(".", "").isalnum():
            errors.append(f"Component '{key}' contains invalid characters: {value}")

    return (len(errors) == 0), components, errors
