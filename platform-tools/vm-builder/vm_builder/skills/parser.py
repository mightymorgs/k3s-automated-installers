"""AST parsing helpers for VM Builder skill generation."""

from __future__ import annotations

import ast
from pathlib import Path


def parse_module_ast(source_file: Path) -> tuple[str, ast.Module] | None:
    """Parse a Python source file into content + AST tree.

    Returns ``None`` when parsing fails, preserving legacy behavior that
    silently skips syntax-invalid files.
    """
    content = source_file.read_text()
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    return content, tree

