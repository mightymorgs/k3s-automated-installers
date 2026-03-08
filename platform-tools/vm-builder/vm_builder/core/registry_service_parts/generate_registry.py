"""Registry generation flow for RegistryService."""

from __future__ import annotations

import logging

from vm_builder.core import registry_generator

logger = logging.getLogger(__name__)


def generate_registry(self) -> dict:
    """Generate registry from configured templates and persist it."""
    if not self._templates_dir or not self._templates_dir.exists():
        raise RuntimeError(
            "Cannot generate registry: templates_dir not configured or missing"
        )

    path_prefix = str(self._templates_dir)
    registry = registry_generator.generate_registry(
        self._templates_dir, path_prefix=path_prefix
    )

    output = self._live_path or self._path
    registry_generator.write_registry(registry, output)
    logger.info(
        "Registry generated: %d apps -> %s",
        len(registry.get("apps", {})),
        output,
    )

    self._data = None
    return registry
