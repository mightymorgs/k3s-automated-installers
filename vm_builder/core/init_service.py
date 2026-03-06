"""Init service -- shared secrets management."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.core.init_service_parts import check_prerequisites as check_prerequisites_part
from vm_builder.core.init_service_parts import constants as constants_part
from vm_builder.core.init_service_parts import get_existing_secrets as get_existing_secrets_part
from vm_builder.core.init_service_parts import write_secrets as write_secrets_part
from vm_builder.core.models import (
    PrereqResult,
    SecretStatus,
    SecretWriteResult,
    SecretWriteStatus,
    SharedSecrets,
)

ALL_SECRET_PATHS = constants_part.ALL_SECRET_PATHS


class _ModuleProxy:
    """Proxy module attributes to current globals for patch-friendly tests."""

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def __getattr__(self, attr: str):
        return getattr(globals()[self._target_name], attr)


def _wire(module, **deps: str) -> None:
    for attr, target_name in deps.items():
        setattr(module, attr, _ModuleProxy(target_name))


_wire(check_prerequisites_part, bws="bws")
_wire(get_existing_secrets_part, bws="bws")
_wire(write_secrets_part, bws="bws")


class InitService:
    """Shared secrets initialization service."""

    ALL_SECRET_PATHS = ALL_SECRET_PATHS

    check_prerequisites = check_prerequisites_part.check_prerequisites
    get_existing_secrets = get_existing_secrets_part.get_existing_secrets
    write_secrets = write_secrets_part.write_secrets


__all__ = [
    "ALL_SECRET_PATHS",
    "InitService",
    "PrereqResult",
    "SecretStatus",
    "SecretWriteResult",
    "SecretWriteStatus",
    "SharedSecrets",
]
