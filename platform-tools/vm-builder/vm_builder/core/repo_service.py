"""Repo service -- clone/pull enterprise repo at startup."""

from __future__ import annotations

import subprocess
from pathlib import Path

from vm_builder.core.repo_service_parts import clone_repo as clone_repo_part
from vm_builder.core.repo_service_parts import ensure_repo as ensure_repo_part
from vm_builder.core.repo_service_parts import get_registry_path as get_registry_path_part
from vm_builder.core.repo_service_parts import get_templates_dir as get_templates_dir_part
from vm_builder.core.repo_service_parts import pull_repo as pull_repo_part
from vm_builder.core.repo_service_parts.models import RepoStatus


class _ModuleProxy:
    """Proxy module attributes to current globals for patch-friendly tests."""

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def __getattr__(self, attr: str):
        return getattr(globals()[self._target_name], attr)


def _wire(module, **deps: str) -> None:
    for attr, target_name in deps.items():
        setattr(module, attr, _ModuleProxy(target_name))


_wire(clone_repo_part, subprocess="subprocess")
_wire(pull_repo_part, subprocess="subprocess")


class RepoService:
    """Manage clone/pull lifecycle for the enterprise templates repo."""

    def __init__(
        self,
        github_repo: str,
        repo_dir: str = "/data/repo",
        registry_subpath: str = "registry/registry.json",
        templates_subpath: str = "vm-builder/vm-builder-templates",
    ):
        self.github_repo = github_repo
        self.repo_dir = Path(repo_dir)
        self.registry_subpath = registry_subpath
        self.templates_subpath = templates_subpath

    ensure_repo = ensure_repo_part.ensure_repo
    _clone = clone_repo_part.clone_repo
    _pull = pull_repo_part.pull_repo
    get_registry_path = get_registry_path_part.get_registry_path
    get_templates_dir = get_templates_dir_part.get_templates_dir


__all__ = ["RepoService", "RepoStatus"]
