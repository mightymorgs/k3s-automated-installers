"""Build _config and _overrides dicts for BWS inventory."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from vm_builder.core.template_service_parts.extract_jinja2_variables import (
    extract_jinja2_variables,
)

logger = logging.getLogger(__name__)


def _coerce_default(raw: str) -> Any:
    """Best-effort coercion of a J2 default string to a Python value."""
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    try:
        return int(raw)
    except (ValueError, TypeError):
        pass
    try:
        return float(raw)
    except (ValueError, TypeError):
        pass
    return raw


def extract_app_defaults(app_id: str, templates_dir: Path) -> dict[str, Any]:
    """Parse all J2 templates for an app, return {var_name: default_value}.

    Scans ``templates_dir/apps/{app_id}/templates/*.yaml.j2``.
    When the same variable appears in multiple files, the first value wins
    (files are processed in sorted order for determinism).
    """
    app_templates = templates_dir / "apps" / app_id / "templates"
    if not app_templates.is_dir():
        return {}

    defaults: dict[str, Any] = {}
    for j2_file in sorted(app_templates.glob("*.yaml.j2")):
        variables = extract_jinja2_variables(j2_file)
        for var_name, meta in variables.items():
            if var_name in defaults:
                continue
            if "default" in meta:
                defaults[var_name] = _coerce_default(meta["default"])
            else:
                defaults[var_name] = None
    return defaults


def populate_config(
    selected_apps: list[str],
    templates_dir: Path,
    user_configs: Optional[dict[str, dict]] = None,
) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Build ``_config`` and ``_overrides`` for BWS inventory.

    Returns
    -------
    (_config, _overrides)
        _config  : {app_id: {var: effective_value, ...}, ...}
        _overrides: {app_id: [var_names that came from user_configs]}
    """
    user_configs = user_configs or {}
    config: dict[str, dict] = {}
    overrides: dict[str, list[str]] = {}

    for app_id in selected_apps:
        defaults = extract_app_defaults(app_id, templates_dir)
        if not defaults and app_id not in user_configs:
            continue

        app_cfg = dict(defaults)
        app_overrides: list[str] = []

        for key, value in user_configs.get(app_id, {}).items():
            app_cfg[key] = value
            app_overrides.append(key)

        config[app_id] = app_cfg
        if app_overrides:
            overrides[app_id] = sorted(app_overrides)

    return config, overrides
