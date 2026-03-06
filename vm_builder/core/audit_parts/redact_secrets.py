"""Secret redaction logic for audit logging."""

from __future__ import annotations

from vm_builder.core.audit_parts.constants import (
    BEARER_RE,
    BWS_TOKEN_RE,
    GHP_TOKEN_RE,
    GITHUB_PAT_RE,
    JSON_SECRET_KEY_RE,
    REDACTED,
    SK_API_KEY_RE,
    TSKEY_API_RE,
    TSKEY_AUTH_RE,
    VAULT_TOKEN_RE,
)


def redact_secrets(text: str) -> str:
    """Redact known secret patterns from text."""
    if not text:
        return text

    text = JSON_SECRET_KEY_RE.sub(rf'\1: "{REDACTED}"', text)
    text = BWS_TOKEN_RE.sub(REDACTED, text)
    text = VAULT_TOKEN_RE.sub(REDACTED, text)
    text = SK_API_KEY_RE.sub(REDACTED, text)
    text = GHP_TOKEN_RE.sub(REDACTED, text)
    text = GITHUB_PAT_RE.sub(REDACTED, text)
    text = TSKEY_AUTH_RE.sub(REDACTED, text)
    text = TSKEY_API_RE.sub(REDACTED, text)
    text = BEARER_RE.sub(rf"\1{REDACTED}", text)
    return text
