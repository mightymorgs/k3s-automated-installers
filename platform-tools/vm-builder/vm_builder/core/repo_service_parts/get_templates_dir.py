"""Templates-directory lookup for RepoService."""

from __future__ import annotations

from typing import Optional


def get_templates_dir(self) -> Optional[str]:
    """Return templates directory inside repo, or None."""
    candidate = self.repo_dir / self.templates_subpath
    if candidate.is_dir():
        return str(candidate)
    return None
