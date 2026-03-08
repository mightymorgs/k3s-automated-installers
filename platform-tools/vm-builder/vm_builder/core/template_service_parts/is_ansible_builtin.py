"""Ansible built-in variable detection helper."""

from __future__ import annotations

from vm_builder.core.template_service_parts.constants import (
    ANSIBLE_BUILTIN_NAMES,
    ANSIBLE_BUILTIN_PREFIXES,
)


def is_ansible_builtin(name: str) -> bool:
    """Return True when a name is a built-in Ansible runtime variable."""
    if name in ANSIBLE_BUILTIN_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in ANSIBLE_BUILTIN_PREFIXES)
