"""Prerequisite checks for HypervisorService."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.core.models import PrereqResult


def check_prerequisites(self) -> PrereqResult:
    """Check BWS CLI + token."""
    try:
        bws.check_prerequisites()
        return PrereqResult(ok=True)
    except EnvironmentError as exc:
        return PrereqResult(ok=False, error=str(exc))
    except BWSError as exc:
        return PrereqResult(ok=False, error=str(exc))
