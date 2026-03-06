"""Object-level redaction helper for audit logging."""

from __future__ import annotations

import json
from typing import Any

from vm_builder.core.audit_parts.redact_secrets import redact_secrets


def redact_obj(obj: Any) -> str:
    """Serialize object as JSON and redact secrets in the serialized text."""
    serialized = json.dumps(obj, default=str)
    return redact_secrets(serialized)
