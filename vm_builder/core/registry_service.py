"""Registry service -- app registry queries. Pure logic, reads JSON file."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from vm_builder.core.registry_service_parts import (
    check_installable as check_installable_part,
)
from vm_builder.core.registry_service_parts import derive_variables as derive_variables_part
from vm_builder.core.registry_service_parts import enrich_app as enrich_app_part
from vm_builder.core.registry_service_parts import generate_registry as generate_registry_part
from vm_builder.core.registry_service_parts import get_app as get_app_part
from vm_builder.core.registry_service_parts import humanize as humanize_part
from vm_builder.core.registry_service_parts import list_apps as list_apps_part
from vm_builder.core.registry_service_parts import load_registry as load_registry_part
from vm_builder.core.registry_service_parts import refresh_registry as refresh_registry_part
from vm_builder.core.registry_service_parts import registry_path as registry_path_part
from vm_builder.core.registry_service_parts import reload_registry as reload_registry_part
from vm_builder.core.registry_service_parts import resolve_deps as resolve_deps_part
from vm_builder.core.registry_service_parts import set_repo_path as set_repo_path_part

_humanize = humanize_part.humanize
_derive_variables = derive_variables_part.derive_variables


class RegistryService:
    """Service for querying and regenerating the app registry."""

    def __init__(
        self,
        registry_path: str,
        templates_dir: Optional[str] = None,
        live_registry_path: Optional[str] = None,
    ):
        self._path = Path(registry_path)
        self._templates_dir = Path(templates_dir) if templates_dir else None
        self._live_path = Path(live_registry_path) if live_registry_path else None
        self._data = None
        self._repo_path: Optional[Path] = None

    set_repo_path = set_repo_path_part.set_repo_path

    _registry_path = registry_path_part.registry_path
    _load = load_registry_part.load_registry
    reload = reload_registry_part.reload_registry

    generate = generate_registry_part.generate_registry
    refresh = refresh_registry_part.refresh_registry

    _enrich_app = enrich_app_part.enrich_app

    list_apps = list_apps_part.list_apps
    get_app = get_app_part.get_app
    resolve_deps = resolve_deps_part.resolve_deps
    check_installable = check_installable_part.check_installable


__all__ = ["RegistryService", "_derive_variables", "_humanize"]
