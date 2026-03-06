"""Prerequisite checks for VM service."""

from __future__ import annotations

import os
import subprocess

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.core.models import PrereqResult


def gh_repo_args() -> list[str]:
    """Return ['--repo', '<owner/repo>'] when GITHUB_REPO is set."""
    repo = os.environ.get("GITHUB_REPO", "").strip()
    return ["--repo", repo] if repo else []


def check_prerequisites(self, check_gh: bool = False) -> PrereqResult:
    """Check BWS (and optionally gh) CLI availability."""
    try:
        bws.check_prerequisites()
    except EnvironmentError as exc:
        return PrereqResult(ok=False, error=str(exc))
    except BWSError as exc:
        return PrereqResult(ok=False, error=str(exc))

    if check_gh:
        try:
            subprocess.run(["gh", "--version"], check=True, capture_output=True)
            subprocess.run(["gh", "auth", "status"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            return PrereqResult(ok=False, error=f"gh CLI not available: {exc}")

    return PrereqResult(ok=True)
