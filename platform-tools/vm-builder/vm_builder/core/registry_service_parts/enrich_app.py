"""App enrichment for RegistryService responses."""

from __future__ import annotations

from vm_builder.core.registry_service_parts.derive_variables import derive_variables
from vm_builder.core.template_service import discover_app_templates


def enrich_app(self, app_id: str, app_data: dict) -> dict:
    """Add derived variables/template paths to one app payload."""
    enriched = {"id": app_id, **app_data}
    enriched["variables"] = derive_variables(
        app_id,
        app_data,
        repo_path=self._repo_path,
    )

    if self._repo_path is not None:
        templates = discover_app_templates(app_id, self._repo_path)
        enriched["template_paths"] = [
            str(template.relative_to(self._repo_path)) for template in templates
        ]

    return enriched
