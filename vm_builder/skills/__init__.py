"""VM Builder repo-skill generation package.

Provides a split, function-first implementation of the legacy
``scripts/generate_vm_builder_skills.py`` script.
"""

from vm_builder.skills.extractor import extract_public_operations
from vm_builder.skills.markdown import render_skill_markdown
from vm_builder.skills.naming import to_kebab
from vm_builder.skills.orchestrator import generate_skills

# Legacy-compatible aliases to ease migration from the monolithic script.
extract_module_operations = extract_public_operations
generate_skill_md = render_skill_markdown
_to_kebab = to_kebab

__all__ = [
    "extract_public_operations",
    "extract_module_operations",
    "generate_skill_md",
    "generate_skills",
    "render_skill_markdown",
    "to_kebab",
    "_to_kebab",
]
