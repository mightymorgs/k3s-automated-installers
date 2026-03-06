"""Registry refresh flow for RegistryService."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from vm_builder.core import registry_generator

logger = logging.getLogger(__name__)


def refresh_registry(
    self,
    templates_dir: str,
    output_path: Optional[str] = None,
) -> dict:
    """Regenerate registry from an external templates directory."""
    templates_path = Path(templates_dir)
    if not templates_path.exists():
        raise RuntimeError(f"Templates directory does not exist: {templates_path}")

    path_prefix = str(templates_path)
    registry = registry_generator.generate_registry(
        templates_path, path_prefix=path_prefix
    )

    destination = (
        Path(output_path) if output_path else (self._live_path or self._path)
    )
    registry_generator.write_registry(registry, destination)
    logger.info(
        "Registry refreshed: %d apps -> %s",
        len(registry.get("apps", {})),
        destination,
    )

    self._data = None
    return registry
