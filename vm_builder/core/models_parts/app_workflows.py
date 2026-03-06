"""Single-app install/configure workflow models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, computed_field


class AppInstallRequest(BaseModel):
    """Request to install a single app on an existing VM."""

    vm_name: str
    app_id: str
    skip_dependency_check: bool = False


class AppInstallResult(BaseModel):
    """Outcome of triggering an app install workflow."""

    workflow_triggered: bool
    vm_name: str
    app_id: str
    run_url: Optional[str] = None
    run_status: Optional[str] = None
    error: Optional[str] = None

    @computed_field
    @property
    def runner_label(self) -> str:
        """GitHub Actions runner label for this VM."""
        return f"vm-{self.vm_name}"


class AppConfigureRequest(BaseModel):
    """Request to configure a single app on an existing VM."""

    vm_name: str
    app_id: str
    config: dict[str, str | int | bool]


class AppConfigureResult(BaseModel):
    """Outcome of triggering an app configure workflow."""

    workflow_triggered: bool
    vm_name: str
    app_id: str
    config_keys: list[str]
    run_url: Optional[str] = None
    run_status: Optional[str] = None
    error: Optional[str] = None

    @computed_field
    @property
    def runner_label(self) -> str:
        """GitHub Actions runner label for this VM."""
        return f"vm-{self.vm_name}"
