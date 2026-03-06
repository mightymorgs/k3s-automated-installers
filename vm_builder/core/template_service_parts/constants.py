"""Constants used across template_service atomic functions."""

from __future__ import annotations

import re

ANSIBLE_BUILTIN_PREFIXES = ("ansible_", "inventory_")

ANSIBLE_BUILTIN_NAMES = frozenset(
    {
        "item",
        "playbook_dir",
        "role_path",
        "hostvars",
        "groups",
        "group_names",
        "lookup",
        "query",
        "omit",
        "true",
        "false",
        "none",
    }
)

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[|}]")
DEFAULT_PATTERN = (
    r"\{{\s*{varname}\s*\|\s*default\(\s*['\"]?([^'\")]+?)['\"]?\s*\)"
)
