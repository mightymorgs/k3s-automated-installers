"""Shared dependencies for API routes."""

import os
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from vm_builder.core.app_install_service import AppInstallService
from vm_builder.core.audit import AuditLogger
from vm_builder.core.init_service import InitService
from vm_builder.core.hypervisor_service import HypervisorService
from vm_builder.core.vm_service import VmService
from vm_builder.core.registry_service import RegistryService
from vm_builder.core.repo_service import RepoService, RepoStatus
from vm_builder.core.health_service import HealthService
from vm_builder.core.refresh_coordinator import RefreshCoordinator
from vm_builder.core.storage_service import StorageService

logger = logging.getLogger(__name__)

# Module-level state for repo sync result (set during startup)
_repo_status: Optional[RepoStatus] = None


@lru_cache
def get_init_service() -> InitService:
    return InitService()


@lru_cache
def get_hypervisor_service() -> HypervisorService:
    return HypervisorService(audit_logger=get_audit_logger())


@lru_cache
def get_vm_service() -> VmService:
    return VmService(audit_logger=get_audit_logger())


@lru_cache
def get_repo_service() -> RepoService:
    """Build RepoService from environment variables."""
    return RepoService(
        github_repo=os.environ.get("GITHUB_REPO", ""),
        repo_dir=os.environ.get("REPO_DIR", "/data/repo"),
    )


def get_repo_status() -> Optional[RepoStatus]:
    """Return the last repo sync status (set during startup)."""
    return _repo_status


def set_repo_status(status: RepoStatus) -> None:
    """Store repo sync status (called by startup event)."""
    global _repo_status
    _repo_status = status


@lru_cache
def get_registry_service() -> RegistryService:
    """Build RegistryService with registry path resolution.

    Resolution order for registry_path:
    1. REGISTRY_PATH env var (explicit override, highest priority)
    2. Cloned repo registry (from RepoService)
    3. Writable fallback at /data/registry.json (data volume)

    TEMPLATES_DIR and LIVE_REGISTRY_PATH are passed through independently.

    When TEMPLATES_DIR is set, it is also used as the repo_path for
    J2 template scanning (after the repo restructure, the templates
    directory IS the repo root containing ``apps/{app}/`` directories).
    """
    templates_dir = os.environ.get("TEMPLATES_DIR") or None
    live_registry_path = os.environ.get("LIVE_REGISTRY_PATH") or None

    # If REGISTRY_PATH is explicitly set, always use it
    explicit_path = os.environ.get("REGISTRY_PATH")
    if explicit_path:
        logger.info("Using explicit REGISTRY_PATH: %s", explicit_path)
        svc = RegistryService(
            registry_path=explicit_path,
            templates_dir=templates_dir,
            live_registry_path=live_registry_path,
        )
    else:
        # Try cloned repo registry
        repo_svc = get_repo_service()
        repo_registry = repo_svc.get_registry_path()
        if repo_registry:
            logger.info("Using cloned repo registry: %s", repo_registry)
            svc = RegistryService(
                registry_path=repo_registry,
                templates_dir=templates_dir,
                live_registry_path=live_registry_path,
            )
        else:
            # Fallback to writable data volume
            fallback = "/data/registry.json"
            logger.info("Using registry fallback: %s", fallback)
            svc = RegistryService(
                registry_path=fallback,
                templates_dir=templates_dir,
                live_registry_path=live_registry_path,
            )

    # Wire repo_path for J2 template scanning.
    # Priority: TEMPLATES_REPO_PATH env > TEMPLATES_DIR env > cloned repo templates dir.
    repo_path = (
        os.environ.get("TEMPLATES_REPO_PATH")
        or templates_dir
        or get_repo_service().get_templates_dir()
    )
    if repo_path:
        resolved = Path(repo_path)
        if resolved.exists():
            logger.info("Setting repo_path for J2 scanning: %s", resolved)
            svc.set_repo_path(resolved)

    return svc


@lru_cache
def get_health_service() -> HealthService:
    return HealthService()


@lru_cache
def get_refresh_coordinator() -> RefreshCoordinator:
    """Build RefreshCoordinator singleton with repo and registry services."""
    cooldown = int(os.environ.get("REFRESH_COOLDOWN_SECONDS", "30"))
    return RefreshCoordinator(
        repo_service=get_repo_service(),
        registry_service=get_registry_service(),
        cooldown_seconds=cooldown,
    )


@lru_cache
def get_audit_logger() -> AuditLogger:
    log_dir = os.environ.get("AUDIT_LOG_DIR", str(Path.home() / ".vm-builder" / "audit"))
    return AuditLogger(log_dir=log_dir)


@lru_cache
def get_app_install_service() -> AppInstallService:
    registry = get_registry_service()
    vm_svc = get_vm_service()
    return AppInstallService(registry=registry, vm_service=vm_svc)


@lru_cache
def get_storage_service() -> StorageService:
    """Build StorageService wired to HypervisorService for SSH resolution."""
    hv_svc = get_hypervisor_service()
    return StorageService(hypervisor_resolver=hv_svc.get_hypervisor)
