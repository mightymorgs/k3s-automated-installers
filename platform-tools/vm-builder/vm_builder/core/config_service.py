"""Config service -- per-app config lifecycle (get, update, reset)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vm_builder import bws
from vm_builder.core.config_service_parts import apply_live as apply_live_part
from vm_builder.core.config_service_parts import get_all_overrides as get_all_overrides_part
from vm_builder.core.config_service_parts import get_app_config as get_app_config_part
from vm_builder.core.config_service_parts import preview_changes as preview_changes_part
from vm_builder.core.config_service_parts import reset_field as reset_field_part
from vm_builder.core.config_service_parts import (
    trigger_live_update as trigger_live_update_part,
)
from vm_builder.core.config_service_parts import update_field as update_field_part
from vm_builder.core.errors import VmNotFoundError
from vm_builder.core.vm_service import VmService


class ConfigService:
    """Service for per-app config field management."""

    def __init__(
        self,
        vm_service: Optional[VmService] = None,
        templates_dir: Optional[Path] = None,
    ):
        self._vm_service = vm_service or VmService()
        self._templates_dir = templates_dir

    def _save_inventory(self, vm_name: str, inventory: dict) -> None:
        """Persist updated inventory back to BWS."""
        key = f"inventory/{vm_name}"
        secrets = bws.list_secrets(filter_key=key)
        if not secrets:
            raise VmNotFoundError(
                f"Inventory key not found: {key}",
                context={"vm_name": vm_name},
            )
        bws.edit_secret(secrets[0]["id"], inventory)

    get_app_config = get_app_config_part.get_app_config
    update_field = update_field_part.update_field
    reset_field = reset_field_part.reset_field
    get_all_overrides = get_all_overrides_part.get_all_overrides
    preview_changes = preview_changes_part.preview_changes
    apply_live = apply_live_part.apply_live
    trigger_live_update = trigger_live_update_part.trigger_live_update


__all__ = ["ConfigService"]
