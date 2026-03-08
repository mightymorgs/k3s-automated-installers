"""App install service -- install/configure apps on running VMs."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Optional

from vm_builder import bws
from vm_builder.core.app_install_service_parts import compute_install_delta as compute_install_delta_part
from vm_builder.core.app_install_service_parts import get_latest_run_url as get_latest_run_url_part
from vm_builder.core.app_install_service_parts import install_apps as install_apps_part
from vm_builder.core.app_install_service_parts import list_installed_apps as list_installed_apps_part
from vm_builder.core.app_install_service_parts import trigger_config_workflow as trigger_config_workflow_part
from vm_builder.core.app_install_service_parts import trigger_install_workflow as trigger_install_workflow_part
from vm_builder.core.app_install_service_parts import uninstall_app as uninstall_app_part
from vm_builder.core.app_install_service_parts import update_inventory_apps as update_inventory_apps_part
from vm_builder.core.errors import AppNotFoundError, BwsSecretError, DependencyError
from vm_builder.core.models import (
    AppStatus,
    AppStatusEnum,
    AppUninstallResult,
    BatchAppInstallRequest,
    BatchAppInstallResult,
    InstalledApp,
)
from vm_builder.core.registry_service import RegistryService
from vm_builder.core.vm_service import VmService

logger = logging.getLogger(__name__)


class _ModuleProxy:
    """Proxy module attributes to current globals for patch-friendly tests."""

    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def __getattr__(self, attr: str):
        return getattr(globals()[self._target_name], attr)


def _wire(module, **deps: str) -> None:
    for attr, target_name in deps.items():
        setattr(module, attr, _ModuleProxy(target_name))


_wire(update_inventory_apps_part, bws="bws")
_wire(uninstall_app_part, bws="bws")
_wire(trigger_install_workflow_part, subprocess="subprocess", time="time", json="json")
_wire(trigger_config_workflow_part, subprocess="subprocess", time="time")
_wire(get_latest_run_url_part, subprocess="subprocess", json="json")


class AppInstallService:
    """Service for installing and managing apps on running VMs."""

    def __init__(self, registry: RegistryService, vm_service: Optional[VmService] = None):
        self._registry = registry
        self._vm_service = vm_service or VmService()

    compute_install_delta = compute_install_delta_part.compute_install_delta
    list_installed_apps = list_installed_apps_part.list_installed_apps

    _update_inventory_apps = update_inventory_apps_part.update_inventory_apps

    install_apps = install_apps_part.install_apps
    uninstall_app = uninstall_app_part.uninstall_app

    _trigger_install_workflow = trigger_install_workflow_part.trigger_install_workflow
    _trigger_config_workflow = trigger_config_workflow_part.trigger_config_workflow
    _get_latest_run_url = get_latest_run_url_part.get_latest_run_url


__all__ = [
    "AppInstallService",
    "AppNotFoundError",
    "AppStatus",
    "AppStatusEnum",
    "AppUninstallResult",
    "BatchAppInstallRequest",
    "BatchAppInstallResult",
    "BwsSecretError",
    "DependencyError",
    "InstalledApp",
    "RegistryService",
    "VmService",
]
