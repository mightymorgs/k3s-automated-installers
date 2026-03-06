"""Clone operation for RepoService."""

from __future__ import annotations

import logging
import subprocess

from vm_builder.core.repo_service_parts.models import RepoStatus

logger = logging.getLogger(__name__)


def clone_repo(self) -> RepoStatus:
    """Clone the configured GitHub repo using gh CLI."""
    try:
        self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "gh",
                "repo",
                "clone",
                self.github_repo,
                str(self.repo_dir),
                "--",
                "--depth",
                "1",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        logger.info("Cloned %s to %s", self.github_repo, self.repo_dir)
        return RepoStatus(
            available=True,
            action="cloned",
            repo_dir=str(self.repo_dir),
        )
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to clone %s: %s", self.github_repo, exc.stderr)
        return RepoStatus(
            available=False,
            action=None,
            error=exc.stderr or str(exc),
        )
    except Exception as exc:
        logger.warning("Unexpected clone error: %s", exc)
        return RepoStatus(
            available=False,
            action=None,
            error=str(exc),
        )
