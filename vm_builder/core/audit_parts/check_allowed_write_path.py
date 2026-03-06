"""BWS write-path guard for audit-integrated secret writes."""

from __future__ import annotations

from vm_builder.core.audit_parts.constants import ALLOWED_WRITE_PATH_PREFIXES


def check_allowed_write_path(key: str) -> None:
    """Raise ValueError if key is outside allowed write prefixes."""
    for prefix in ALLOWED_WRITE_PATH_PREFIXES:
        if key.startswith(prefix):
            return
    raise ValueError(
        f"BWS write to '{key}' denied: not under allowed prefixes "
        f"{ALLOWED_WRITE_PATH_PREFIXES}"
    )
