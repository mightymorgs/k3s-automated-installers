"""Batch app-installation models."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class AppStatusEnum(str, Enum):
    """Per-app installation status."""

    PENDING = "pending"
    INSTALLING = "installing"
    INSTALLED = "installed"
    CONFIGURING = "configuring"
    READY = "ready"
    INSTALL_FAILED = "install_failed"
    CONFIG_FAILED = "config_failed"


class AppStatus(BaseModel):
    """Status of a single app during install/configure pipeline."""

    app_id: str
    status: AppStatusEnum
    workflow_run_url: Optional[str] = None
    error: Optional[str] = None


class BatchAppInstallRequest(BaseModel):
    """Request to install app(s) on a running VM (batch)."""

    apps: list[str]
    app_configs: dict[str, dict] = {}


class BatchAppInstallResult(BaseModel):
    """Result of a batch app install request."""

    vm_name: str
    apps_requested: list[str]
    apps_to_install: list[str]
    statuses: list[AppStatus]


class InstalledApp(BaseModel):
    """An app currently installed on a VM."""

    app_id: str
    display_name: Optional[str] = None
    category: Optional[str] = None
    status: AppStatusEnum = AppStatusEnum.READY


class AppUninstallResult(BaseModel):
    """Result of uninstalling an app from a VM."""

    vm_name: str
    app_id: str
    removed_from_inventory: bool
    k8s_resources_remain: bool = True
    message: str
