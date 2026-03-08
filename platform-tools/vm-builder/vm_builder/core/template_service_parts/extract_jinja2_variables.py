"""Single-template Jinja2 variable extraction."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import jinja2
import jinja2.meta

from vm_builder.core.template_service_parts.constants import VAR_RE
from vm_builder.core.template_service_parts.extract_defaults import extract_defaults
from vm_builder.core.template_service_parts.humanize import humanize
from vm_builder.core.template_service_parts.is_ansible_builtin import is_ansible_builtin

logger = logging.getLogger(__name__)

_PATH_SUFFIXES = re.compile(
    r"(?:_dir|_directory|_mount|_mount_point|_mount_path|_root)$", re.IGNORECASE
)
_STORAGE_PATH = re.compile(
    r"(?:storage|data|config|log|backup|cache|mount|volume|nfs|smb)_path$",
    re.IGNORECASE,
)
_PATH_EXACT = {"mount_point", "root_folder"}


def extract_jinja2_variables(file_path: Path) -> dict[str, dict]:
    """Extract undeclared variables from one Jinja2 template."""
    file_path = Path(file_path)
    if not file_path.exists():
        return {}

    try:
        template_text = file_path.read_text()
    except OSError:
        return {}

    if not template_text.strip():
        return {}

    variable_names: set[str] = set()
    env = jinja2.Environment()
    env.globals = {}
    try:
        ast = env.parse(template_text)
        variable_names = jinja2.meta.find_undeclared_variables(ast)
    except jinja2.TemplateSyntaxError:
        logger.debug("AST parse failed for %s, using regex fallback", file_path)
        for match in VAR_RE.finditer(template_text):
            variable_names.add(match.group(1))

    variable_names = {
        name for name in variable_names if not is_ansible_builtin(name)
    }
    if not variable_names:
        return {}

    defaults = extract_defaults(template_text, variable_names)

    source_file = str(file_path.name)
    result: dict[str, dict] = {}
    for name in sorted(variable_names):
        entry: dict = {
            "label": humanize(name),
            "type": "string",
            "required": False,
            "source_file": source_file,
        }
        if _PATH_SUFFIXES.search(name) or _STORAGE_PATH.search(name) or name.lower() in _PATH_EXACT:
            entry["type"] = "directory"
        if name in defaults:
            entry["default"] = defaults[name]
        result[name] = entry

    return result
