"""Variable derivation helpers for RegistryService."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from vm_builder.core.registry_service_parts.humanize import humanize
from vm_builder.core.template_service import (
    enrich_with_bws_state,
    extract_app_variables,
)


def derive_variables(
    app_id: str,
    app_data: dict,
    repo_path: Optional[Path] = None,
) -> dict:
    """Auto-generate UI config variables for an app."""
    existing = app_data.get("variables", {})
    bws_state = app_data.get("bws_state", {})

    if repo_path is not None and Path(repo_path).exists():
        # Extract all J2 template variables, then overlay metadata vars
        # (metadata takes precedence for descriptions, types, etc.)
        variables = extract_app_variables(app_id, repo_path)
        variables = enrich_with_bws_state(variables, bws_state, app_id)
        if existing:
            variables.update(existing)

        ingress = app_data.get("ingress", {})
        if ingress.get("enabled"):
            subdomain = ingress.get("subdomain", "")
            if subdomain and "subdomain" not in variables:
                variables["subdomain"] = {
                    "label": "Subdomain",
                    "description": (
                        f"Subdomain for web access (e.g. {subdomain}.yourdomain.com)"
                    ),
                    "type": "string",
                    "default": subdomain,
                    "required": False,
                }

            port = ingress.get("service_port")
            if port and "service_port" not in variables:
                variables["service_port"] = {
                    "label": "Service Port",
                    "description": "Internal service port",
                    "type": "integer",
                    "default": port,
                    "required": False,
                }

        return variables

    # No repo_path — use metadata vars if available
    if existing:
        return existing

    variables: dict = {}
    for entry in bws_state.get("reads", []):
        path = entry.get("path", "")
        purpose = entry.get("purpose", "")
        match = re.match(r"inventory/shared/secrets/[^/]+/(.+)$", path)
        if not match:
            continue
        field_name = match.group(1)
        is_password = any(
            keyword in field_name for keyword in ("password", "secret", "key", "token")
        )
        variables[field_name] = {
            "label": humanize(field_name),
            "description": purpose,
            "type": "secret" if is_password else "string",
            "required": False,
            "bws_path": path,
        }

    ingress = app_data.get("ingress", {})
    if ingress.get("enabled"):
        subdomain = ingress.get("subdomain", "")
        if subdomain:
            variables["subdomain"] = {
                "label": "Subdomain",
                "description": f"Subdomain for web access (e.g. {subdomain}.yourdomain.com)",
                "type": "string",
                "default": subdomain,
                "required": False,
            }
        port = ingress.get("service_port")
        if port:
            variables["service_port"] = {
                "label": "Service Port",
                "description": "Internal service port",
                "type": "integer",
                "default": port,
                "required": False,
            }

    return variables
