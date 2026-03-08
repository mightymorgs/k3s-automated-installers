"""Default-value extraction helper for Jinja2 templates."""

from __future__ import annotations

import re

from vm_builder.core.template_service_parts.constants import DEFAULT_PATTERN


def extract_defaults(template_text: str, variable_names: set[str]) -> dict[str, str]:
    """Extract default(...) values for a known set of variable names."""
    defaults: dict[str, str] = {}
    for var_name in variable_names:
        pattern = DEFAULT_PATTERN.format(varname=re.escape(var_name))
        match = re.search(pattern, template_text)
        if match:
            defaults[var_name] = match.group(1).strip()
    return defaults
