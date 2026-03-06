"""BWS (Bitwarden Secrets Manager) CLI wrapper."""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Union

from vm_builder.bws_parts import check_prerequisites as check_prerequisites_part
from vm_builder.bws_parts import create_secret as create_secret_part
from vm_builder.bws_parts import delete_secret as delete_secret_part
from vm_builder.bws_parts import edit_secret as edit_secret_part
from vm_builder.bws_parts import get_secret as get_secret_part
from vm_builder.bws_parts import get_secret_by_id as get_secret_by_id_part
from vm_builder.bws_parts import list_secrets as list_secrets_part
from vm_builder.bws_parts import secret_exists as secret_exists_part
from vm_builder.core.audit import AuditLogger, check_allowed_write_path

_DEFAULT_PROJECT_ID = "517eeecd-c99b-4387-9e77-b35c0066a149"


def get_project_id() -> str:
    """Return BWS project ID from env var, falling back to hardcoded default."""
    return os.getenv("BWS_PROJECT_ID") or _DEFAULT_PROJECT_ID

_audit_logger: Optional[AuditLogger] = None


def set_audit_logger(logger: Optional[AuditLogger]) -> None:
    """Set module-level audit logger (or None to disable)."""
    global _audit_logger
    _audit_logger = logger


def get_audit_logger() -> Optional[AuditLogger]:
    """Return current module-level audit logger."""
    return _audit_logger


class BWSError(Exception):
    """Base exception for BWS operations."""


check_prerequisites = check_prerequisites_part.check_prerequisites
create_secret = create_secret_part.create_secret
get_secret = get_secret_part.get_secret
get_secret_by_id = get_secret_by_id_part.get_secret_by_id
list_secrets = list_secrets_part.list_secrets
edit_secret = edit_secret_part.edit_secret
delete_secret = delete_secret_part.delete_secret
secret_exists = secret_exists_part.secret_exists

__all__ = [
    "AuditLogger",
    "get_project_id",
    "BWSError",
    "check_prerequisites",
    "create_secret",
    "delete_secret",
    "edit_secret",
    "get_audit_logger",
    "get_secret",
    "get_secret_by_id",
    "list_secrets",
    "secret_exists",
    "set_audit_logger",
]
