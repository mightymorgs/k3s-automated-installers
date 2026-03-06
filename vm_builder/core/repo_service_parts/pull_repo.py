"""Pull operation for RepoService."""

from __future__ import annotations

import logging
import os
import subprocess

from vm_builder.core.repo_service_parts.models import RepoStatus

logger = logging.getLogger(__name__)


def _configure_git_auth(repo_dir: str, github_repo: str) -> None:
    """Set remote URL with embedded token so git pull can authenticate."""
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        return
    auth_url = f"https://x-access-token:{token}@github.com/{github_repo}.git"
    subprocess.run(
        ["git", "-C", repo_dir, "remote", "set-url", "origin", auth_url],
        capture_output=True,
        text=True,
        timeout=10,
    )


def pull_repo(self) -> RepoStatus:
    """Fetch + reset to match remote HEAD (read-only deployment clone)."""
    try:
        repo = str(self.repo_dir)
        _configure_git_auth(repo, self.github_repo)
        subprocess.run(
            ["git", "-C", repo, "fetch", "origin"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Detect default branch from remote HEAD
        result = subprocess.run(
            ["git", "-C", repo, "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            branch = result.stdout.strip().removeprefix("refs/remotes/origin/")
        else:
            branch = "main"
        subprocess.run(
            ["git", "-C", repo, "reset", "--hard", f"origin/{branch}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info("Synced %s to origin/%s", self.repo_dir, branch)
        return RepoStatus(
            available=True,
            action="pulled",
            repo_dir=repo,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning("Pull failed in %s (stale): %s", self.repo_dir, exc.stderr)
        return RepoStatus(
            available=True,
            action="stale",
            error=exc.stderr or str(exc),
            repo_dir=repo,
        )
    except Exception as exc:
        logger.warning("Unexpected pull error: %s", exc)
        return RepoStatus(
            available=True,
            action="stale",
            error=str(exc),
            repo_dir=str(self.repo_dir),
        )
