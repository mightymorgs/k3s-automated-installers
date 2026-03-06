"""Template service -- Jinja2 variable extraction from app templates."""

from __future__ import annotations

from vm_builder.core.template_service_parts import constants as constants_part
from vm_builder.core.template_service_parts import discover_app_templates as discover_app_templates_part
from vm_builder.core.template_service_parts import enrich_with_bws_state as enrich_with_bws_state_part
from vm_builder.core.template_service_parts import extract_app_variables as extract_app_variables_part
from vm_builder.core.template_service_parts import extract_defaults as extract_defaults_part
from vm_builder.core.template_service_parts import extract_jinja2_variables as extract_jinja2_variables_part
from vm_builder.core.template_service_parts import humanize as humanize_part
from vm_builder.core.template_service_parts import is_ansible_builtin as is_ansible_builtin_part
from vm_builder.core.template_service_parts import scan_playbook_template_refs as scan_playbook_template_refs_part

ANSIBLE_BUILTIN_PREFIXES = constants_part.ANSIBLE_BUILTIN_PREFIXES
ANSIBLE_BUILTIN_NAMES = constants_part.ANSIBLE_BUILTIN_NAMES
_VAR_RE = constants_part.VAR_RE
_DEFAULT_PATTERN = constants_part.DEFAULT_PATTERN

_humanize = humanize_part.humanize
_is_ansible_builtin = is_ansible_builtin_part.is_ansible_builtin
_extract_defaults = extract_defaults_part.extract_defaults

extract_jinja2_variables = extract_jinja2_variables_part.extract_jinja2_variables
discover_app_templates = discover_app_templates_part.discover_app_templates
extract_app_variables = extract_app_variables_part.extract_app_variables
enrich_with_bws_state = enrich_with_bws_state_part.enrich_with_bws_state
scan_playbook_template_refs = scan_playbook_template_refs_part.scan_playbook_template_refs

__all__ = [
    "ANSIBLE_BUILTIN_NAMES",
    "ANSIBLE_BUILTIN_PREFIXES",
    "discover_app_templates",
    "enrich_with_bws_state",
    "extract_app_variables",
    "extract_jinja2_variables",
    "scan_playbook_template_refs",
]
