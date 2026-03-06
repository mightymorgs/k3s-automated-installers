"""Existing-secret status checks for InitService."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.core.models import SecretStatus


def get_existing_secrets(self) -> list[SecretStatus]:
    """Return exists/missing status for all known shared secret paths."""
    return [
        SecretStatus(path=path, exists=bws.secret_exists(path))
        for path in self.ALL_SECRET_PATHS
    ]
