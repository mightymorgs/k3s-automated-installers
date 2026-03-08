"""Public operation extraction from VM Builder Python modules."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from vm_builder.skills.constants import (
    MODULE_RESOURCE_MAP,
    SKIP_METHODS,
)
from vm_builder.skills.imports import collect_and_resolve_imports
from vm_builder.skills.naming import to_kebab
from vm_builder.skills.parser import parse_module_ast


def _extract_signature(source: str, node: ast.AST, fallback_name: str) -> str:
    """Extract a function signature line from source text."""
    sig = ast.get_source_segment(source, node)
    if not sig:
        return f"def {fallback_name}(...)"

    sig_line = ""
    for line in sig.split("\n"):
        sig_line += line
        if ")" in line and ":" in line:
            break
        sig_line += "\n"

    return sig_line.strip().rstrip(":")


def _resource_for_module(module_name: str) -> str:
    """Resolve module name to repo skill resource name."""
    return MODULE_RESOURCE_MAP.get(module_name, to_kebab(module_name))


def extract_public_operations(source_file: Path) -> list[dict[str, Any]]:
    """Extract public methods/functions from a source module.

    Returned dicts follow the legacy script contract:
    ``class_name``, ``name``, ``resource``, ``operation``, ``signature``,
    ``docstring``, ``source_file``, ``imports``, ``depends_on``.
    """
    parsed = parse_module_ast(source_file)
    if parsed is None:
        return []

    content, tree = parsed
    resource = _resource_for_module(source_file.stem)
    imports, depends_on = collect_and_resolve_imports(tree, resource=resource)

    operations: list[dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue

            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name.startswith("_") or item.name in SKIP_METHODS:
                    continue

                operations.append(
                    {
                        "class_name": node.name,
                        "name": item.name,
                        "resource": resource,
                        "operation": to_kebab(item.name),
                        "signature": _extract_signature(content, item, item.name),
                        "docstring": ast.get_docstring(item) or "",
                        "source_file": str(source_file),
                        "imports": imports,
                        "depends_on": depends_on,
                    }
                )
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue

            operations.append(
                {
                    "class_name": None,
                    "name": node.name,
                    "resource": resource,
                    "operation": to_kebab(node.name),
                    "signature": _extract_signature(content, node, node.name),
                    "docstring": ast.get_docstring(node) or "",
                    "source_file": str(source_file),
                    "imports": imports,
                    "depends_on": depends_on,
                }
            )

    return operations

