"""Repo availability/sync entrypoint for RepoService."""

from __future__ import annotations

from vm_builder.core.repo_service_parts.models import RepoStatus


def ensure_repo(self) -> RepoStatus:
    """Clone if missing, pull if present; return availability status."""
    if not self.github_repo:
        return RepoStatus(
            available=False,
            error="GITHUB_REPO not configured",
        )

    git_dir = self.repo_dir / ".git"
    if git_dir.is_dir():
        return self._pull()
    return self._clone()
