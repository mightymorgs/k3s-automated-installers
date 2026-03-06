"""Registry path lookup for RepoService."""

from __future__ import annotations

from typing import Optional


def get_registry_path(self) -> Optional[str]:
    """Return path to registry.json inside repo, or None."""
    candidate = self.repo_dir / self.registry_subpath
    if candidate.is_file():
        return str(candidate)
    return None
