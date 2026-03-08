"""Initializer method for AuditLogger."""

from __future__ import annotations

from pathlib import Path

from vm_builder.core.audit_parts.constants import DEFAULT_LOG_DIR


def init_logger(self, log_dir: str | Path | None = None) -> None:
    """Initialize audit log directory."""
    self.log_dir = Path(log_dir or DEFAULT_LOG_DIR)
    self.log_dir.mkdir(parents=True, exist_ok=True)
