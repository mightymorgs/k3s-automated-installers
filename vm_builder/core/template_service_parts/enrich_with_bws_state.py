"""BWS-secret enrichment for extracted template variables."""

from __future__ import annotations

import copy

from vm_builder.core.template_service_parts.humanize import humanize


def enrich_with_bws_state(
    variables: dict[str, dict],
    bws_state: dict,
    app_id: str,
) -> dict[str, dict]:
    """Overlay BWS secret metadata onto J2-derived variables."""
    enriched = copy.deepcopy(variables)

    reads = bws_state.get("reads", [])
    if not reads:
        return enriched

    prefix = f"inventory/shared/secrets/{app_id}/"
    for entry in reads:
        path = entry.get("path", "")
        purpose = entry.get("purpose", "")
        if not path.startswith(prefix):
            continue

        field_name = path[len(prefix):]
        if not field_name:
            continue

        if field_name in enriched:
            enriched[field_name]["type"] = "secret"
            enriched[field_name]["bws_path"] = path
            enriched[field_name]["description"] = purpose
            continue

        enriched[field_name] = {
            "label": humanize(field_name),
            "type": "secret",
            "required": False,
            "bws_path": path,
            "description": purpose,
        }

    return enriched
