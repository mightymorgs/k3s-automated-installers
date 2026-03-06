"""App-record construction for discovered app metadata."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from vm_builder.core.registry_generator_parts.relative_template_path import (
    relative_template_path,
)
from vm_builder.core.template_service_parts.extract_app_variables import (
    extract_app_variables,
)

logger = logging.getLogger(__name__)


def build_app_record(
    app_dir: Path,
    deploy_file: Path,
    metadata: dict[str, Any],
    install_playbooks: list[Path],
    config_playbooks: list[Path],
    templates_dir: Path,
    path_prefix: Optional[str] = None,
    config_requires: Optional[dict[Path, list[str]]] = None,
) -> dict[str, Any]:
    """Build one registry app record from discovered metadata/playbooks."""
    all_playbooks = install_playbooks + config_playbooks
    app_name = app_dir.name

    install_paths = [
        relative_template_path(path, templates_dir, path_prefix)
        for path in install_playbooks
    ]
    config_details = []
    for pb in config_playbooks:
        rel = relative_template_path(pb, templates_dir, path_prefix)
        requires = (
            config_requires.get(pb, [app_name]) if config_requires else [app_name]
        )
        config_details.append({"path": rel, "requires_apps": requires})

    config_paths = [d["path"] for d in config_details]
    all_paths = install_paths + config_paths

    ui_metadata = metadata.get("ui", {})

    # J2 templates are the source of truth for configurable vars.
    # Metadata vars override J2 defaults (for labels, descriptions, types).
    j2_vars = extract_app_variables(app_name, templates_dir)
    vars_metadata = {**j2_vars, **metadata.get("vars", {})}
    bws_state = metadata.get("bws_state", {})
    credentials = metadata.get("credentials", {})
    wiring = metadata.get("wiring", {})
    ingress = metadata.get("ingress", {})
    sso = metadata.get("sso", {})

    # Resolve namespace: explicit metadata > ingress.namespace > app name
    namespace = (
        metadata.get("namespace")
        or ingress.get("namespace")
        or app_name
    )

    return {
        "id": app_name,
        "namespace": namespace,
        "playbook_path": relative_template_path(
            deploy_file, templates_dir, path_prefix
        ),
        "playbooks": all_paths,
        "install_playbooks": install_paths,
        "config_playbooks": config_paths,
        "config_playbook_details": config_details,
        "playbook_count": len(all_paths),
        "install_count": len(install_paths),
        "config_count": len(config_paths),
        "display_name": ui_metadata.get("display_name", app_name.title()),
        "description": ui_metadata.get("description", metadata.get("description", "")),
        "icon": ui_metadata.get("icon", "box"),
        "category": ui_metadata.get("category", "Uncategorized"),
        "docs_url": ui_metadata.get("docs_url"),
        "port": ui_metadata.get("port"),
        "nodeport": ui_metadata.get("nodeport"),
        "dependencies": metadata.get("dependencies", []),
        "provides": metadata.get("provides", []),
        "tags": metadata.get("tags", []),
        "parallel_safe": metadata.get("parallel_safe", True),
        "idempotent": metadata.get("idempotent", True),
        "estimated_duration": metadata.get("estimated_duration"),
        "compatibility": metadata.get("compatibility", {}),
        "variables": vars_metadata,
        "bws_state": bws_state,
        "credentials": credentials,
        "wiring": wiring,
        "ingress": ingress,
        "sso": sso,
    }
