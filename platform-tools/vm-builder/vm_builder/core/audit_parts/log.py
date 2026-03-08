"""Core log write method for AuditLogger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from vm_builder.core.audit_parts.redact_obj import redact_obj


def log(
    self,
    event_type: str,
    detail: dict[str, Any],
    duration_ms: int = 0,
) -> None:
    """Write one redacted JSONL audit entry."""
    try:
        now = datetime.now(timezone.utc)
        redacted_detail = redact_obj(detail)
        try:
            parsed_detail = json.loads(redacted_detail)
        except json.JSONDecodeError:
            parsed_detail = {"_raw": redacted_detail}

        entry = {
            "timestamp": now.isoformat(),
            "event_type": event_type,
            "detail": parsed_detail,
            "duration_ms": duration_ms,
        }
        log_file = self.log_dir / f"audit-{now.strftime('%Y-%m-%d')}.jsonl"
        with open(log_file, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        # Audit logging must never crash the audited operation.
        pass
