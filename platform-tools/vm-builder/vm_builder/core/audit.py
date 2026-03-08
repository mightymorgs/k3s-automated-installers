"""Audit logger with automatic secrets redaction for vm-builder."""

from __future__ import annotations

from typing import Any

from vm_builder.core.audit_parts import check_allowed_write_path as check_allowed_write_path_part
from vm_builder.core.audit_parts import constants as constants_part
from vm_builder.core.audit_parts import init_logger as init_logger_part
from vm_builder.core.audit_parts import log as log_part
from vm_builder.core.audit_parts import log_api_request as log_api_request_part
from vm_builder.core.audit_parts import log_bws_write as log_bws_write_part
from vm_builder.core.audit_parts import log_gh_trigger as log_gh_trigger_part
from vm_builder.core.audit_parts import log_httpx_call as log_httpx_call_part
from vm_builder.core.audit_parts import redact_obj as redact_obj_part
from vm_builder.core.audit_parts import redact_secrets as redact_secrets_part

_BWS_TOKEN_RE = constants_part.BWS_TOKEN_RE
_VAULT_TOKEN_RE = constants_part.VAULT_TOKEN_RE
_SK_API_KEY_RE = constants_part.SK_API_KEY_RE
_GHP_TOKEN_RE = constants_part.GHP_TOKEN_RE
_GITHUB_PAT_RE = constants_part.GITHUB_PAT_RE
_TSKEY_AUTH_RE = constants_part.TSKEY_AUTH_RE
_TSKEY_API_RE = constants_part.TSKEY_API_RE
_BEARER_RE = constants_part.BEARER_RE
_JSON_SECRET_KEY_RE = constants_part.JSON_SECRET_KEY_RE
_REDACTED = constants_part.REDACTED

ALLOWED_WRITE_PATH_PREFIXES = constants_part.ALLOWED_WRITE_PATH_PREFIXES
_DEFAULT_LOG_DIR = constants_part.DEFAULT_LOG_DIR

redact_secrets = redact_secrets_part.redact_secrets


def _redact_obj(obj: Any) -> str:
    """Serialize object to JSON and redact secrets in serialized text."""
    return redact_obj_part.redact_obj(obj)


check_allowed_write_path = check_allowed_write_path_part.check_allowed_write_path


class AuditLogger:
    """Append-only JSONL audit logger with automatic secret redaction."""

    __init__ = init_logger_part.init_logger

    log = log_part.log
    log_api_request = log_api_request_part.log_api_request
    log_bws_write = log_bws_write_part.log_bws_write
    log_gh_trigger = log_gh_trigger_part.log_gh_trigger
    log_httpx_call = log_httpx_call_part.log_httpx_call


__all__ = [
    "ALLOWED_WRITE_PATH_PREFIXES",
    "AuditLogger",
    "check_allowed_write_path",
    "redact_secrets",
]
