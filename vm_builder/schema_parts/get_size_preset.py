"""Size preset accessor for VM hardware defaults."""

from __future__ import annotations

from typing import Any, Dict

from vm_builder.schema_parts.constants import SIZE_PRESETS


def get_size_preset(size: str) -> Dict[str, Any]:
    """Return hardware defaults for a named size preset."""
    if size not in SIZE_PRESETS:
        raise KeyError(
            f"Unknown size preset: {size}. "
            f"Valid options: {', '.join(SIZE_PRESETS.keys())}"
        )
    return SIZE_PRESETS[size].copy()
