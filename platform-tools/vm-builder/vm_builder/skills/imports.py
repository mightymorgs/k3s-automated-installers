"""Import analysis and dependency resolution for VM Builder skills."""

from __future__ import annotations

import ast

from vm_builder.skills.constants import IMPORT_DEPENDS_MAP


def collect_vm_builder_imports(tree: ast.AST) -> set[str]:
    """Collect ``vm_builder`` imports from a parsed AST tree."""
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("vm_builder"):
                imports.add(node.module)
                for alias in node.names:
                    imports.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("vm_builder"):
                    imports.add(alias.name)

    return imports


def resolve_depends_on(
    imports: set[str],
    resource: str,
    service: str = "vm-builder",
) -> list[str]:
    """Map imports to ``depends_on`` skill path prefixes."""
    depends_on: set[str] = set()

    for imported in imports:
        for prefix, skill_prefix in IMPORT_DEPENDS_MAP.items():
            if imported.startswith(prefix):
                depends_on.add(skill_prefix)
                break

    # Remove self dependency if inferred.
    depends_on.discard(f"{service}/{resource}")
    return sorted(depends_on)


def collect_and_resolve_imports(
    tree: ast.AST,
    resource: str,
    service: str = "vm-builder",
) -> tuple[list[str], list[str]]:
    """Collect vm_builder imports and resolve sorted ``depends_on`` values."""
    imports = collect_vm_builder_imports(tree)
    depends_on = resolve_depends_on(imports, resource=resource, service=service)
    return sorted(imports), depends_on

