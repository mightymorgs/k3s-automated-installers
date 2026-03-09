"""Generate docs/IDI-INDEX.md and docs/VM-BUILDER-INDEX.md programmatically.

Walks Python/TypeScript source trees, extracts module docstrings, CLI entry
points, MCP tools, API routes, external dependencies, and architectural
patterns via AST analysis.  Optionally queries CGC FalkorDB for call chains.

Usage::

    python scripts/generate_indexes.py              # regenerate both indexes
    python scripts/generate_indexes.py --check       # dry-run, exit 1 if stale
    python scripts/generate_indexes.py --no-cgc      # skip CGC FalkorDB queries
"""

from __future__ import annotations

import argparse
import ast
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Directories to unconditionally exclude from all file discovery.
_IGNORE_DIRS: set[str] = {
    "__pycache__", ".venv", "venv", "node_modules", ".git",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".tox", ".eggs", ".idea", ".vscode",
}

# Suffixes that mark an entire directory as ignored (e.g. idi.egg-info).
_IGNORE_DIR_SUFFIXES: tuple[str, ...] = (".egg-info",)


def _is_ignored(path: Path) -> bool:
    """Return True if any component of *path* matches an ignored directory."""
    for part in path.parts:
        if part in _IGNORE_DIRS:
            return True
        if part.endswith(_IGNORE_DIR_SUFFIXES):
            return True
    return False


# ---------------------------------------------------------------------------
# Package grouping definitions
# ---------------------------------------------------------------------------
# Each entry: (section_level, section_title, directory relative to package root,
#              include_subdirs).  section_level "##" = top section, "####" = nested.
# Order matters — first match wins for files.

IDI_GROUPS: list[tuple[str, str, str]] = [
    ("###", "Top-Level Module", ""),
    ("###", "Common Utilities", "common"),
    ("###", "Generation — OpenAPI-to-Skill Pipeline", "generation"),
    ("####", "generation/adapters/ — Schema Family Adapters", "generation/adapters"),
    ("####", "generation/dep_adapters/ — Dependency Detection Adapters", "generation/dep_adapters"),
    ("####", "generation/crd/ — CRD Schema Processing", "generation/crd"),
    ("###", "Enrichment — Context7 Cross-App Extraction", "enrichment"),
]

VM_BUILDER_GROUPS: list[tuple[str, str, str]] = [
    ("###", "Top-Level Modules", ""),
    ("###", "CLI Atomic — Command Registration", "cli_atomic"),
    ("###", "Commands — CLI Command Implementation", "commands"),
    ("####", "commands/hypervisor_cmd/", "commands/hypervisor_cmd"),
    ("####", "commands/init_cmd/", "commands/init_cmd"),
    ("####", "commands/validate_cmd/", "commands/validate_cmd"),
    ("####", "commands/vm_cmd/", "commands/vm_cmd"),
    ("####", "commands/storage_cmd/", "commands/storage_cmd"),
    ("####", "commands/schema_cmd/", "commands/schema_cmd"),
    ("####", "commands/ingress_cmd/", "commands/ingress_cmd"),
    ("####", "commands/health_cmd/", "commands/health_cmd"),
    ("####", "commands/registry_cmd/", "commands/registry_cmd"),
    ("###", "API — FastAPI Application", "api"),
    ("####", "api/routes/", "api/routes"),
    ("###", "Core — Service Layer", "core"),
    ("###", "Core Atomic Parts — Service Implementations", "_parts_"),
    ("###", "BWS Parts", "bws_parts"),
    ("###", "Schema Parts", "schema_parts"),
    ("###", "Template Sidecars", "template_sidecars"),
]


# ---------------------------------------------------------------------------
# Docstring extraction
# ---------------------------------------------------------------------------

def _first_line(docstring: str | None) -> str:
    """Return first sentence/line of a docstring, stripped of leading articles."""
    if not docstring:
        return "(no docstring)"
    line = docstring.strip().split("\n")[0].rstrip(".")
    return line + "."


def _infer_docstring_from_path(filepath: Path) -> str | None:
    """Infer a description from the file name and directory when no docstring exists."""
    name = filepath.stem
    parent = filepath.parent.name
    grandparent = filepath.parent.parent.name if filepath.parent.parent else ""

    # __init__.py
    if name == "__init__":
        return f"Package init for {parent}/."

    # Common filename patterns
    filename_hints: dict[str, str] = {
        "errors": "Error types and exception definitions.",
        "exceptions": "Exception definitions.",
        "types": "Type aliases and type definitions.",
        "models": "Data model definitions.",
        "schemas": "Schema definitions.",
        "constants": "Constants and configuration values.",
        "config": "Configuration loading and defaults.",
        "utils": "Utility helpers.",
        "helpers": "Helper functions.",
    }
    if name in filename_hints:
        return filename_hints[name]

    # Directory-based hints
    parts = str(filepath).replace("\\", "/")
    if "/api/routes/" in parts:
        resource = name.replace("_", " ")
        return f"API route handlers for {resource}."
    if "/cli/" in parts or "/cli_atomic/" in parts:
        cmd = name.replace("_command", "").replace("_", " ")
        return f"CLI command: {cmd}."
    if "/commands/" in parts:
        cmd = name.replace("_", " ")
        return f"CLI implementation: {cmd}."
    if "_parts/" in parts or "_parts" in parent:
        service = grandparent.removesuffix("_service_parts").removesuffix("_parts")
        action = name.replace("_", " ")
        return f"Atomic part: {action} ({service})."
    if "/adapters/" in parts:
        adapter = name.replace("_", " ")
        return f"Adapter: {adapter}."
    if "/executors/" in parts:
        executor = name.replace("_executor", "").replace("_", " ")
        return f"Executor: {executor}."
    if "/extractors/" in parts:
        extractor = name.replace("_extractor", "").replace("_", " ")
        return f"Extractor: {extractor}."

    return None


def extract_module_docstring(filepath: Path) -> str:
    """Extract first line of module docstring via AST.

    Falls back to: first class docstring, then path-based heuristic.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
        doc = ast.get_docstring(tree)
        if doc:
            return _first_line(doc)
        # Fallback 1: first class docstring
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_doc = ast.get_docstring(node)
                if class_doc:
                    return _first_line(class_doc)
        # Fallback 2: path-based heuristic
        hint = _infer_docstring_from_path(filepath)
        if hint:
            return hint
        return "(no docstring)"
    except (SyntaxError, UnicodeDecodeError):
        return "(parse error)"


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_py_files(pkg_root: Path) -> list[Path]:
    """Collect all .py files under pkg_root, sorted, excluding ignored dirs."""
    return sorted(f for f in pkg_root.rglob("*.py") if not _is_ignored(f.relative_to(pkg_root)))


def _rel(filepath: Path, pkg_root: Path) -> str:
    """Relative path from package root, using forward slashes."""
    return str(filepath.relative_to(pkg_root)).replace("\\", "/")


def _dir_of(rel_path: str) -> str:
    """Directory portion of a relative path (empty string for top-level files)."""
    parts = rel_path.split("/")
    if len(parts) == 1:
        return ""
    return "/".join(parts[:-1])


# ---------------------------------------------------------------------------
# Grouping logic
# ---------------------------------------------------------------------------

def _is_parts_dir(dir_path: str) -> bool:
    """Check if a directory is a _parts/ directory under core/."""
    return dir_path.startswith("core/") and dir_path.endswith("_parts")


def assign_group(rel_path: str, groups: list[tuple[str, str, str]], pkg_name: str) -> str | None:
    """Find the best matching group directory for a file path."""
    file_dir = _dir_of(rel_path)

    if pkg_name == "vm_builder" and _is_parts_dir(file_dir):
        return "_parts_"

    best_match = None
    best_len = -1
    for _, _, group_dir in groups:
        if group_dir == "_parts_":
            continue
        if group_dir == "":
            if file_dir == "" and (best_match is None or best_len < 0):
                best_match = ""
                best_len = 0
        elif (file_dir == group_dir or file_dir.startswith(group_dir + "/")) and len(group_dir) > best_len:
            best_match = group_dir
            best_len = len(group_dir)

    return best_match


# ---------------------------------------------------------------------------
# Section 0: Cheat Sheet
# ---------------------------------------------------------------------------

_IDI_CHEAT_SHEET: list[dict[str, Any]] = [
    {
        "task": "Add new OpenAPI spec",
        "desc": "`catalog/manifest.yaml` + `idi/generation/adapters/` if new format",
        "check": ["generation/adapters"],
    },
    {
        "task": "Add dependency adapter",
        "desc": "`idi/generation/dep_adapters/` (new module) + register in `merge.py`",
        "check": ["generation/dep_adapters", "generation/dep_adapters/merge.py"],
    },
    {
        "task": "Add CRD schema handler",
        "desc": "`idi/generation/crd/` (new module)",
        "check": ["generation/crd"],
    },
    {
        "task": "Add schema family adapter",
        "desc": "`idi/generation/adapters/` (new module)",
        "check": ["generation/adapters"],
    },
    {
        "task": "Add Context7 enrichment",
        "desc": "`idi/enrichment/` (new module)",
        "check": ["enrichment"],
    },
]

_VM_CHEAT_SHEET: list[dict[str, Any]] = [
    {
        "task": "Add API route",
        "desc": "`vm_builder/api/routes/` (new module) + register in `app.py`",
        "check": ["api/routes", "api/app.py"],
    },
    {
        "task": "Add CLI command",
        "desc": "`vm_builder/cli_atomic/` (registration) + `vm_builder/commands/` (impl)",
        "check": ["cli_atomic", "commands"],
    },
    {
        "task": "Add service method",
        "desc": "`vm_builder/core/{svc}_service_parts/` (new part file) + facade re-export in `core/{svc}_service.py`",
        "check": ["core"],
    },
    {
        "task": "Add new core service",
        "desc": "`vm_builder/core/` (facade) + `_parts/` subpackage + `api/deps.py` (DI)",
        "check": ["core", "api/deps.py"],
    },
    {
        "task": "Add app to templates",
        "desc": "`vm-builder-templates/apps/{app}/` with `.idi-meta.yaml` sidecar",
        "check": [],  # Checked relative to templates dir
    },
    {
        "task": "Change VM schema",
        "desc": "`vm_builder/schema_parts/`",
        "check": ["schema_parts"],
    },
    {
        "task": "Add template sidecar detector",
        "desc": "`vm_builder/template_sidecars/` (new module)",
        "check": ["template_sidecars"],
    },
]


def generate_cheat_sheet(pkg_name: str, pkg_root: Path) -> str:
    """Generate a task → where-to-edit cheat sheet section."""
    templates = _IDI_CHEAT_SHEET if pkg_name == "idi" else _VM_CHEAT_SHEET

    lines = ["## Quick Reference: Where to Edit", ""]
    lines.append("| Task | Where to Edit |")
    lines.append("|---|---|")

    for entry in templates:
        # Verify at least one check path exists
        checks = entry["check"]
        if checks:
            found = any((pkg_root / c).exists() for c in checks)
            if not found:
                print(f"WARNING [{pkg_name}]: Cheat sheet path not found for '{entry['task']}': {checks}", file=sys.stderr)
                continue
        lines.append(f"| {entry['task']} | {entry['desc']} |")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 1 generation
# ---------------------------------------------------------------------------

def _pad_to(text: str, width: int) -> str:
    """Pad text with spaces to reach width."""
    return text + " " * max(1, width - len(text))


def generate_section1(
    pkg_name: str,
    pkg_root: Path,
    groups: list[tuple[str, str, str]],
    display_name: str,
    cgc: Any = None,
) -> tuple[str, int]:
    """Generate the Section 1 markdown text and total file count."""
    files = collect_py_files(pkg_root)

    grouped: dict[str, list[tuple[str, str]]] = {}
    for _, _, gdir in groups:
        grouped[gdir] = []

    for f in files:
        rel = _rel(f, pkg_root)
        gdir = assign_group(rel, groups, pkg_name)
        if gdir is not None:
            grouped[gdir].append((rel, extract_module_docstring(f)))

    parts_subdirs: dict[str, list[tuple[str, str]]] = {}
    if "_parts_" in grouped:
        for rel, doc in grouped["_parts_"]:
            subdir = _dir_of(rel)
            parts_subdirs.setdefault(subdir, []).append((rel, doc))

    today = datetime.date.today().isoformat()
    total = sum(len(v) for v in grouped.values())
    section_num = 1
    subsection_num = 0

    lines: list[str] = []

    # Header
    if pkg_name == "idi":
        lines.append("# IDI Module Index")
        lines.append("")
        lines.append("> **For LLMs.** Comprehensive static index of all Python modules in `idi/`.")
        lines.append("> Use this as a lookup table for troubleshooting and expansion — every module, entry point,")
        lines.append("> CLI command, MCP tool, and external dependency is catalogued here.")
    else:
        lines.append("# VM Builder Module Index")
        lines.append("")
        lines.append("> **For LLMs.** Comprehensive static index of all modules in `vm-builder/`.")
        lines.append("> Use this as a lookup table for troubleshooting and expansion — every module, entry point,")
        lines.append("> API route, and external dependency is catalogued here.")

    lines.append("")
    if cgc:
        mode = "CGC-enriched — call-graph edges and import chains from CodeGraphContext FalkorDB"
    else:
        mode = "AST-only mode — no call-graph enrichment"
    lines.append(f"*Generated by `scripts/generate_indexes.py` on {today} ({mode})*")
    lines.append("")
    lines.append(f"**Module count:** {total} | **Package:** `{pkg_name}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## {section_num}. Static Module Index")
    lines.append("")

    top_level_groups = [g for g in groups if g[0] == "###"]
    lines.append(f"{total} files across {len(top_level_groups)} package areas. Each line: `path — one-line description`.")

    stats_rows: list[tuple[str, int]] = []

    for level, title, gdir in groups:
        entries = grouped.get(gdir, [])
        if gdir == "_parts_":
            count = sum(len(v) for v in parts_subdirs.values())
        else:
            count = len(entries)

        if count == 0:
            continue

        lines.append("")

        noun = "file" if count == 1 else "files"
        if level == "###":
            subsection_num += 1
            lines.append(f"### {section_num}.{subsection_num} {title} ({count} {noun})")
        else:
            lines.append(f"#### {title} ({count} {noun})")

        if gdir == "_parts_":
            parts_total = 0
            for subdir in sorted(parts_subdirs.keys()):
                sub_entries = parts_subdirs[subdir]
                parts_total += len(sub_entries)
                subdir_name = subdir.split("/")[-1] if "/" in subdir else subdir
                lines.append("")
                lines.append(f"#### core/{subdir_name}/ ({len(sub_entries)} files)")
                lines.append("```")
                _emit_entries(lines, sub_entries, pkg_root)
                lines.append("```")
            stats_rows.append((title, parts_total))
        else:
            lines.append("```")
            _emit_entries(lines, entries, pkg_root)
            lines.append("```")
            stats_rows.append((title, count))

    lines.append("")
    lines.append(f"### {section_num}.{subsection_num + 1} Summary Statistics")
    lines.append("")
    lines.append("| Package Area | Files |")
    lines.append("|---|---|")
    for name, count in stats_rows:
        lines.append(f"| {name} | {count} |")
    lines.append(f"| **Total** | **{total}** |")

    # Module tags summary
    tag_counts: dict[str, int] = {}
    for f in files:
        rel = _rel(f, pkg_root)
        for tag in _classify_module_tags(rel, pkg_name):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    if tag_counts:
        lines.append("")
        lines.append(f"### {section_num}.{subsection_num + 2} Module Tags")
        lines.append("")
        lines.append("Machine-readable edit-safety hints (available in JSON sidecar).")
        lines.append("")
        lines.append("| Tag | Count | Meaning |")
        lines.append("|---|---|---|")
        tag_descriptions = {
            "entrypoint": "CLI/server entry point — change with care",
            "service": "Service facade — preferred edit target for new capabilities",
            "atomic_part": "Atomic implementation file — edit only for targeted fixes",
            "io_boundary": "Makes external I/O calls (BWS, HTTP, subprocess)",
            "model": "Schema, types, or data model definitions",
            "cli_wrapper": "CLI registration/command wrapper",
            "api_route": "FastAPI route handler",
        }
        for tag in sorted(tag_counts, key=lambda t: -tag_counts[t]):
            desc = tag_descriptions.get(tag, "")
            lines.append(f"| `{tag}` | {tag_counts[tag]} | {desc} |")

    return "\n".join(lines), total


def _classify_module_tags(rel_path: str, pkg_name: str) -> list[str]:
    """Assign machine-readable edit-safety tags to a module based on its path.

    Tags:
        entrypoint   — CLI/server entry point or __main__.py
        service      — Service facade (core/*.py without _parts)
        atomic_part  — Atomic implementation file inside _parts/
        io_boundary  — Module that makes external I/O calls
        model        — Schema, types, or data model definitions
        cli_wrapper  — CLI registration/command wrappers
        api_route    — FastAPI route handler
    """
    tags: list[str] = []
    parts = rel_path.split("/")
    filename = parts[-1]
    dir_path = "/".join(parts[:-1]) if len(parts) > 1 else ""

    # Entrypoints
    if filename in ("__main__.py", "server.py", "app.py"):
        tags.append("entrypoint")
    if filename == "cli.py" and dir_path:
        tags.append("entrypoint")

    # Service facades (core/*.py but not _parts/)
    if dir_path == "core" and "_parts" not in filename:
        if filename.endswith("_service.py") or filename.endswith("_generator.py"):
            tags.append("service")

    # Atomic parts
    if "_parts" in dir_path:
        tags.append("atomic_part")

    # CLI wrappers
    if dir_path in ("cli", "cli_atomic", "commands") or dir_path.startswith("commands/"):
        tags.append("cli_wrapper")

    # API routes
    if dir_path == "api/routes":
        tags.append("api_route")
    if dir_path == "api" and filename == "deps.py":
        tags.append("io_boundary")

    # IO boundaries (heuristic: files dealing with external systems)
    io_patterns = [
        "bws_client", "bws_state_tracker", "bws",
        "spec_loader", "download_specs", "crd_schemas",
        "executor",
    ]
    stem = filename.replace(".py", "")
    if any(stem == pat or stem.endswith("_executor") for pat in io_patterns):
        tags.append("io_boundary")

    # Models / schemas
    if dir_path in ("schema_parts",) or filename in ("graph_ops.py", "fact_model.py"):
        tags.append("model")
    if "schema" in filename and "schema_routes" not in filename:
        tags.append("model")

    return tags


def _emit_entries(lines: list[str], entries: list[tuple[str, str]], pkg_root: Path) -> None:
    """Emit path — description lines inside a code block."""
    if not entries:
        return
    max_path_len = max(len(rel) for rel, _ in entries)
    pad_width = max_path_len + 1
    for rel, doc in entries:
        lines.append(f"{_pad_to(rel, pad_width)}— {doc}")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _parse_file(filepath: Path) -> ast.Module | None:
    """Parse a Python file, returning the AST or None on failure."""
    try:
        source = filepath.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
        return None


def _get_decorator_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    """Extract decorator information from a function definition.

    Returns list of dicts with keys: name, args, attr (for method-call decorators).
    """
    results = []
    for dec in node.decorator_list:
        info: dict[str, Any] = {}
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Name):
                info["name"] = func.id
            elif isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name):
                    info["name"] = func.value.id
                    info["attr"] = func.attr
            info["args"] = []
            for arg in dec.args:
                if isinstance(arg, ast.Constant):
                    info["args"].append(arg.value)
            info["kwargs"] = {}
            for kw in dec.keywords:
                if kw.arg and isinstance(kw.value, ast.Constant):
                    info["kwargs"][kw.arg] = kw.value.value
        elif isinstance(dec, ast.Attribute):
            if isinstance(dec.value, ast.Name):
                info["name"] = dec.value.id
                info["attr"] = dec.attr
        elif isinstance(dec, ast.Name):
            info["name"] = dec.id
        if info:
            results.append(info)
    return results


def _get_func_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, str]]:
    """Extract function parameters with type annotations."""
    params = []
    for arg in node.args.args:
        if arg.arg == "self":
            continue
        p: dict[str, str] = {"name": arg.arg}
        if arg.annotation:
            p["type"] = ast.unparse(arg.annotation)
        params.append(p)

    # Defaults are right-aligned to args
    defaults = node.args.defaults
    num_defaults = len(defaults)
    num_args = len(node.args.args)
    for i, d in enumerate(defaults):
        arg_idx = num_args - num_defaults + i
        if arg_idx >= 0 and arg_idx < len(params):
            if isinstance(d, ast.Constant):
                params[arg_idx]["default"] = repr(d.value)

    return params


def _get_router_prefix(tree: ast.Module) -> str:
    """Extract APIRouter prefix from module-level assignment."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "APIRouter":
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        return kw.value.value
    return ""


# ---------------------------------------------------------------------------
# CGC connection helper
# ---------------------------------------------------------------------------

def _cgc_connect() -> Any:
    """Connect to CGC FalkorDB via codegraphcontext. Returns driver-like wrapper or None."""
    try:
        from codegraphcontext.core.database_falkordb import FalkorDBManager
        mgr = FalkorDBManager()
        driver = mgr.get_driver()
        # Verify connectivity with a simple query
        with driver.session() as session:
            session.run("RETURN 1")
        return driver
    except Exception:
        return None


def _cgc_call_chain(driver: Any, entry_func: str, max_depth: int = 4) -> list[str]:
    """Query CGC FalkorDB for call chain from a function. Returns list of called function names."""
    if not driver:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (f:Function {name: $entry})-[:CALLS*1..4]->(t:Function) "
                "RETURN DISTINCT t.name AS name, t.file AS file",
                entry=entry_func,
            )
            return [r["name"] for r in result if r["name"]]
    except Exception:
        return []


def _cgc_file_imports(driver: Any, module_name: str) -> list[str]:
    """Query CGC FalkorDB for files that import a given module."""
    if not driver:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (f:File)-[:IMPORTS]->(t:File) "
                "WHERE t.path CONTAINS $module "
                "RETURN DISTINCT f.path AS path",
                module=module_name,
            )
            return [r["path"] for r in result if r["path"]]
    except Exception:
        return []


def _cgc_entry_point_chains(driver: Any, entry_funcs: list[str]) -> list[tuple[str, list[str]]]:
    """Query CGC for call chains from multiple entry point functions."""
    results = []
    for func in entry_funcs:
        callees = _cgc_call_chain(driver, func, max_depth=2)
        if callees:
            results.append((func, callees))
    return results


# ---------------------------------------------------------------------------
# Section 2: Entry Point Map
# ---------------------------------------------------------------------------

def _detect_click_commands(cli_dir: Path) -> list[dict[str, str]]:
    """AST-scan CLI directory for Click command/group decorators."""
    commands: list[dict[str, str]] = []
    if not cli_dir.exists():
        return commands

    for py_file in sorted(cli_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        tree = _parse_file(py_file)
        if not tree:
            continue

        rel = py_file.name
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec_info in _get_decorator_info(node):
                name = dec_info.get("name", "")
                attr = dec_info.get("attr", "")
                args = dec_info.get("args", [])
                # @click.command() or @click.group()
                if name == "click" and attr in ("command", "group"):
                    cmd_name = args[0] if args else node.name
                    commands.append({
                        "name": cmd_name,
                        "func": node.name,
                        "file": rel,
                        "type": attr,
                    })
                # @group_var.command("name") or @group_var.group("name")
                elif attr in ("command", "group") and name != "click":
                    cmd_name = args[0] if args else node.name
                    commands.append({
                        "name": cmd_name,
                        "func": node.name,
                        "file": rel,
                        "type": attr,
                        "parent": name,
                    })
    return commands


def _detect_main_modules(pkg_root: Path) -> list[dict[str, str]]:
    """Find __main__.py files and determine their entry module."""
    entries = []
    for main_file in sorted(pkg_root.rglob("__main__.py")):
        rel = _rel(main_file, pkg_root)
        # Derive the python -m path
        parts = rel.replace("/__main__.py", "").split("/")
        module_path = ".".join(parts)
        entries.append({
            "module": module_path,
            "file": rel,
        })
    return entries


def _detect_pyproject_scripts(pyproject_path: Path) -> list[dict[str, str]]:
    """Parse pyproject.toml for [project.scripts] entry points using tomllib."""
    scripts: list[dict[str, str]] = []
    if not pyproject_path.exists():
        return scripts
    try:
        import tomllib
    except ModuleNotFoundError:          # Python < 3.11 fallback
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        for cmd, target in data.get("project", {}).get("scripts", {}).items():
            scripts.append({"command": cmd, "target": target})
    except Exception:
        pass
    return scripts


def generate_entry_point_map_idi(pkg_root: Path, cgc: Any) -> str:
    """Generate Section 2 for IDI package."""
    lines = ["## 2. Entry Point Map", "",
             "Every CLI command and MCP tool traced through the package layers.", ""]

    # 2.1 CLI Entry Points
    lines.append("### 2.1 CLI Entry Points")
    lines.append("")
    lines.append("```")

    # Detect from pyproject.toml
    scripts = _detect_pyproject_scripts(ROOT / "platform-tools" / "idi" / "pyproject.toml")
    for s in scripts:
        if "idi" in s["command"]:
            lines.append(f"{s['command']:<33} → {s['target']}")
    lines.append("")

    # Detect Click commands from idi/cli/
    cli_dir = pkg_root / "cli"
    commands = _detect_click_commands(cli_dir)
    for cmd in commands:
        parent = cmd.get("parent", "")
        if parent:
            lines.append(f"idi {parent} {cmd['name']:<22} → cli/{cmd['file']}")
        else:
            lines.append(f"idi {cmd['name']:<29} → cli/{cmd['file']}")

    # Detect __main__.py entry points
    lines.append("")
    main_modules = _detect_main_modules(pkg_root)
    for mod in main_modules:
        pkg_prefix = "idi"
        mod_path = f"{pkg_prefix}.{mod['module']}"
        lines.append(f"python -m {mod_path:<25} → {mod['file']}")

    # MCP server entry
    mcp_server = pkg_root / "mcp" / "server.py"
    if mcp_server.exists():
        lines.append(f"python -m idi.mcp.server        → mcp/server.py (FastMCP stdio transport)")

    lines.append("```")
    lines.append("")

    # Call trees for major entry points (template-based with path verification)
    call_trees = _idi_call_trees(pkg_root)
    for tree in call_trees:
        lines.append(f"### {tree['title']}")
        lines.append("")
        lines.append("```")
        for line in tree["lines"]:
            lines.append(line)
        lines.append("```")
        lines.append("")

    # CGC-enriched call chains for key entry points
    if cgc:
        cgc_entries = ["cli", "generate_all", "download_all", "generate_service"]
        cgc_chains = _cgc_entry_point_chains(cgc, cgc_entries)
        if cgc_chains:
            lines.append("### CGC Call Graph (dynamic)")
            lines.append("")
            lines.append("*Call chains extracted from CodeGraphContext FalkorDB graph.*")
            lines.append("")
            for func_name, callees in cgc_chains:
                lines.append(f"**{func_name}() calls:** {', '.join(f'`{c}`' for c in callees[:15])}")
                if len(callees) > 15:
                    lines.append(f"  + {len(callees) - 15} more")
                lines.append("")

    # Command Summary table
    lines.append("### Command Summary")
    lines.append("")
    lines.append("| Entry Point | Module | External I/O |")
    lines.append("|---|---|---|")

    summary = _idi_command_summary(pkg_root)
    for row in summary:
        lines.append(f"| `{row[0]}` | `{row[1]}` | {row[2]} |")

    return "\n".join(lines)


def _idi_call_trees(pkg_root: Path) -> list[dict]:
    """Generate call tree diagrams for IDI entry points.

    Template-based with filesystem path verification.
    Only emits trees where at least one check_file exists.
    """
    trees = []

    templates = [
        {
            "title": "2.2 idi.generation generate",
            "lines": [
                "generation/cli.py → generate()",
                "  ├── generation/spec_loader.py → load_spec()",
                "  │   └── HTTP fetch or file read for OpenAPI schema",
                "  ├── generation/context.py → GeneratorContext (shared state)",
                "  │",
                "  │ Pass 1 — Discovery:",
                "  ├── generation/path_extractor.py → extract_operations()",
                "  ├── generation/resource_namer.py → build_resource_name()",
                "  │",
                "  │ Pass 2 — Emit:",
                "  ├── generation/field_extractor.py → extract_fields()",
                "  ├── generation/adapters/*.py → detect API family",
                "  ├── generation/dep_adapters/registry.py → detect dependencies",
                "  │   ├── dep_adapters/body_fk.py → FK from request body",
                "  │   ├── dep_adapters/path_deps.py → parent from path params",
                "  │   ├── dep_adapters/discriminator.py → OpenAPI discriminator",
                "  │   ├── dep_adapters/output_detection.py → response ID fields",
                "  │   ├── dep_adapters/target_inference.py → name-based inference",
                "  │   └── dep_adapters/merge.py → confidence merge",
                "  ├── generation/polymorphic.py → resolve polymorphic targets",
                "  ├── generation/fact_model.py → canonicalize fact URIs",
                "  └── generation/output_writer.py → write JSON artifacts",
                "      └── Output: service/resource/{manifest.json, operations/*.json, fields/*.json}",
            ],
            "check_files": [
                "generation/cli.py", "generation/spec_loader.py", "generation/context.py",
                "generation/path_extractor.py", "generation/resource_namer.py",
                "generation/field_extractor.py", "generation/output_writer.py",
                "generation/polymorphic.py", "generation/fact_model.py",
                "generation/dep_adapters/registry.py", "generation/dep_adapters/body_fk.py",
                "generation/dep_adapters/merge.py",
            ],
        },
        {
            "title": "2.3 idi.enrichment — Context7 Cross-App Extraction",
            "lines": [
                "enrichment/context7.py → extract cross-app dependencies",
                "  ├── enrichment/schemas.py → Pydantic models for enrichment data",
                "  └── Output: cross-app dependency YAML",
            ],
            "check_files": [
                "enrichment/context7.py", "enrichment/schemas.py",
            ],
        },
    ]

    for tmpl in templates:
        # Skip templates where no check_files exist
        existing = [c for c in tmpl.get("check_files", []) if (pkg_root / c).exists()]
        if not existing:
            continue
        verified_lines = list(tmpl["lines"])
        for check in tmpl.get("check_files", []):
            if not (pkg_root / check).exists():
                verified_lines.append(f"  (MISSING: {check})")
        trees.append({"title": tmpl["title"], "lines": verified_lines})

    return trees


def _idi_command_summary(pkg_root: Path) -> list[tuple[str, str, str]]:
    """Generate command summary rows for IDI."""
    rows = []
    # Static list verified against filesystem
    entries = [
        ("idi-generate", "generation/generate_all.py", "HTTP (specs), File I/O"),
        ("idi-download", "generation/download_specs.py", "HTTP (specs), File I/O"),
        ("idi.generation", "generation/cli.py", "HTTP (specs), File I/O"),
    ]
    for cmd, module, io in entries:
        if (pkg_root / module).exists():
            rows.append((cmd, module, io))
    return rows


def generate_entry_point_map_vm(pkg_root: Path, cgc: Any) -> str:
    """Generate Section 2 for VM Builder package."""
    lines = ["## 2. Entry Point Map", "",
             "Every CLI command traced through 5 layers: "
             "`cli_atomic → commands → commands/*_cmd → core/*_service → core/*_service_parts`.", ""]

    # Architecture pattern
    lines.append("### Architecture Pattern")
    lines.append("")
    lines.append("```")
    lines.append("cli.py → cli_atomic/group.py (root Click group)")

    # Detect registered commands from cli_atomic/
    cli_atomic_dir = pkg_root / "cli_atomic"
    if cli_atomic_dir.exists():
        reg_files = sorted(f for f in cli_atomic_dir.glob("*.py")
                          if f.name not in ("__init__.py", "group.py"))
        for i, f in enumerate(reg_files):
            connector = "└──" if i == len(reg_files) - 1 else "├──"
            # Resolve actual dispatch target via AST import scan
            target = _resolve_cli_atomic_target(f, pkg_root)
            if not target:
                cmd_name = f.stem.replace("_command", "").replace("_", " ")
                target = f"commands/{cmd_name.split()[0]}.py"
            lines.append(f"  {connector} cli_atomic/{f.name:<30} → {target}")
    lines.append("```")
    lines.append("")

    # Call trees for major VM Builder commands
    vm_trees = _vm_call_trees(pkg_root)
    for tree in vm_trees:
        lines.append(f"### {tree['title']}")
        lines.append("")
        lines.append("```")
        for line in tree["lines"]:
            lines.append(line)
        lines.append("```")
        lines.append("")

    # CGC-enriched call chains for key entry points
    if cgc:
        cgc_entries = ["main", "init_shared_secrets", "create_vm", "validate_playbook"]
        cgc_chains = _cgc_entry_point_chains(cgc, cgc_entries)
        if cgc_chains:
            lines.append("### CGC Call Graph (dynamic)")
            lines.append("")
            lines.append("*Call chains extracted from CodeGraphContext FalkorDB graph.*")
            lines.append("")
            for func_name, callees in cgc_chains:
                lines.append(f"**{func_name}() calls:** {', '.join(f'`{c}`' for c in callees[:15])}")
                if len(callees) > 15:
                    lines.append(f"  + {len(callees) - 15} more")
                lines.append("")

    # Command Summary table
    lines.append("### Command Summary")
    lines.append("")
    lines.append("| CLI Command | Atomic Handler | Core Service | External I/O |")
    lines.append("|---|---|---|---|")

    summary = _vm_command_summary(pkg_root)
    for row in summary:
        lines.append(f"| `{row[0]}` | `{row[1]}` | `{row[2]}` | {row[3]} |")

    return "\n".join(lines)


def _resolve_cli_atomic_target(cli_file: Path, pkg_root: Path) -> str | None:
    """Follow imports in a cli_atomic file to find its dispatch target."""
    tree = _parse_file(cli_file)
    if not tree:
        return None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            # Skip common utility imports
            if mod.startswith("click") or mod == "__future__":
                continue
            if "vm_builder." in mod or mod.startswith("vm_builder."):
                parts = mod.replace("vm_builder.", "").replace(".", "/")
                return parts + ".py"
    return None


def _vm_call_trees(pkg_root: Path) -> list[dict]:
    """Generate call tree diagrams for VM Builder entry points."""
    templates = [
        {
            "title": "vm-builder init",
            "lines": [
                "cli_atomic/init_command.py",
                "  → commands/init.py → init_shared_secrets()",
                "    → commands/init_cmd/run.py → init_shared_secrets()",
                "      ├── commands/init_cmd/output.py → print_banner()",
                "      ├── core/init_service.py → InitService()",
                "      │   └── core/init_service_parts/check_prerequisites.py",
                "      │       └── bws.py → check_prerequisites()",
                "      ├── commands/init_cmd/config.py → load_config()",
                "      ├── commands/init_cmd/prompts.py → collect_shared_secrets()",
                "      │   ├── _prompt_tailscale()",
                "      │   ├── _prompt_terraform()",
                "      │   ├── _prompt_cloudflare()",
                "      │   ├── _prompt_github()",
                "      │   ├── _prompt_hashicorp()",
                "      │   ├── _prompt_console()",
                "      │   └── _prompt_ansible()",
                "      ├── commands/init_cmd/output.py → print_summary()",
                "      └── core/init_service_parts/write_secrets.py → write_secrets()",
                "          ├── bws.secret_exists()",
                "          ├── bws.list_secrets()",
                "          ├── bws.edit_secret()",
                "          └── bws.create_secret()",
            ],
            "check_files": [
                "cli_atomic/init_command.py", "commands/init.py",
                "commands/init_cmd/run.py", "core/init_service.py",
            ],
        },
        {
            "title": "vm-builder hypervisor bootstrap",
            "lines": [
                "cli_atomic/hypervisor_command.py",
                "  → commands/hypervisor.py → generate_bootstrap_script()",
                "    → commands/hypervisor_cmd/run.py",
                "      ├── core/hypervisor_service.py → HypervisorService()",
                "      │   └── core/hypervisor_service_parts/check_prerequisites.py",
                "      ├── commands/hypervisor_cmd/prompts.py → resolve_hypervisor_config()",
                "      ├── core/hypervisor_service_parts/generate_bootstrap_script.py",
                "      │   ├── bws.get_secret() [tailscale/oauth, github/pat, versions]",
                "      │   ├── hypervisor_service_parts/create_tailscale_auth_key.py",
                "      │   │   └── httpx → Tailscale API",
                "      │   ├── hypervisor_service_parts/create_github_runner_token.py",
                "      │   │   └── httpx → GitHub API",
                "      │   ├── hypervisor_service_parts/create_hypervisor_inventory.py",
                "      │   │   └── bws.create_secret()",
                "      │   └── Jinja2 → templates/hypervisor-bootstrap.sh.j2",
                "      └── hypervisor_service_parts/write_bootstrap_script.py",
            ],
            "check_files": [
                "cli_atomic/hypervisor_command.py", "commands/hypervisor.py",
                "commands/hypervisor_cmd/run.py", "core/hypervisor_service.py",
            ],
        },
        {
            "title": "vm-builder vm create",
            "lines": [
                "cli_atomic/vm_command.py",
                "  → commands/vm.py → create_vm_inventory()",
                "    → commands/vm_cmd/create.py",
                "      ├── commands/vm_cmd/common.py → print_banner()",
                "      ├── core/vm_service.py → VmService()",
                "      │   └── vm_service_parts/check_prerequisites.py",
                "      ├── commands/vm_cmd/create_request.py → load_config(), build_request()",
                "      ├── commands/vm_cmd/output.py → print_create_inputs()",
                "      ├── vm_service_parts/create_vm.py",
                "      │   ├── bws.get_secret() [console/username]",
                "      │   ├── vm_service_parts/generate_ssh_keypair.py → subprocess(ssh-keygen)",
                "      │   ├── vm_service_parts/build_inventory.py → schema.validate_inventory()",
                "      │   ├── bws.secret_exists()",
                "      │   ├── bws.list_secrets()",
                "      │   ├── bws.edit_secret()",
                "      │   └── bws.create_secret()",
                "      └── commands/vm_cmd/output.py → print_create_result()",
            ],
            "check_files": [
                "cli_atomic/vm_command.py", "commands/vm.py",
                "commands/vm_cmd/create.py", "core/vm_service.py",
            ],
        },
        {
            "title": "vm-builder vm deploy",
            "lines": [
                "cli_atomic/vm_command.py",
                "  → commands/vm.py → deploy_vm()",
                "    → commands/vm_cmd/deploy.py",
                "      ├── commands/vm_cmd/common.py → print_banner()",
                "      ├── vm_service_parts/deploy_vm.py",
                "      │   ├── vm_service_parts/get_vm.py → bws.get_secret()",
                "      │   ├── core/workflow_names.py → WorkflowNames.provision(platform)",
                "      │   ├── vm_service_parts/auto_detect_hypervisor.py → bws.list_secrets()",
                "      │   ├── subprocess(gh workflow run)",
                "      │   ├── AuditLogger.log_gh_trigger()",
                "      │   └── vm_service_parts/fetch_latest_run.py → subprocess(gh run list)",
                "      └── commands/vm_cmd/output.py → print_deploy_result()",
            ],
            "check_files": [
                "cli_atomic/vm_command.py", "commands/vm.py",
                "commands/vm_cmd/deploy.py", "core/vm_service.py",
            ],
        },
        {
            "title": "vm-builder registry generate",
            "lines": [
                "cli_atomic/registry_command.py",
                "  → core/registry_generator.py → generate_registry()",
                "    ├── registry_generator_parts/discover_apps.py",
                "    │   ├── registry_generator_parts/find_entry_playbook.py",
                "    │   ├── registry_generator_parts/extract_playbook_metadata.py",
                "    │   ├── registry_generator_parts/find_install_playbooks.py",
                "    │   ├── registry_generator_parts/find_config_playbooks.py",
                "    │   └── registry_generator_parts/build_app_record.py",
                "    ├── registry_generator_parts/build_provides_map.py",
                "    ├── registry_generator_parts/resolve_dependencies.py",
                "    └── registry_generator_parts/topological_sort.py",
                "  → registry_generator_parts/write_registry.py",
            ],
            "check_files": [
                "cli_atomic/registry_command.py", "core/registry_generator.py",
            ],
        },
        # Fix 16: vm list call tree
        {
            "title": "vm-builder vm list",
            "lines": [
                "cli_atomic/vm_command.py",
                "  → commands/vm.py → list_vms()",
                "    → commands/vm_cmd/list.py",
                "      ├── core/vm_service.py → VmService.list_vms()",
                "      │   └── vm_service_parts/list_vms.py → bws.list_secrets()",
                "      └── commands/vm_cmd/output.py → print_vm_list()",
            ],
            "check_files": [
                "cli_atomic/vm_command.py", "commands/vm.py",
                "commands/vm_cmd/list.py",
            ],
        },
        # Fix 16: vm delete call tree
        {
            "title": "vm-builder vm delete",
            "lines": [
                "cli_atomic/vm_command.py",
                "  → commands/vm.py → delete_vm()",
                "    → commands/vm_cmd/delete.py",
                "      ├── commands/vm_cmd/common.py → print_banner()",
                "      ├── vm_service_parts/get_vm.py → bws.get_secret()",
                "      ├── vm_service_parts/delete_vm.py",
                "      │   ├── bws.list_secrets()",
                "      │   └── bws.edit_secret() [mark deleted]",
                "      └── commands/vm_cmd/output.py → print_delete_result()",
            ],
            "check_files": [
                "cli_atomic/vm_command.py", "commands/vm.py",
                "commands/vm_cmd/delete.py",
            ],
        },
        # Fix 16: validate call tree
        {
            "title": "vm-builder validate",
            "lines": [
                "cli_atomic/validate_command.py",
                "  → commands/validate.py → validate()",
                "    → commands/validate_cmd/run.py",
                "      ├── core/vm_service.py → VmService.list_vms()",
                "      │   └── vm_service_parts/list_vms.py → bws.list_secrets()",
                "      └── commands/validate_cmd/output.py → print_validation_result()",
            ],
            "check_files": [
                "cli_atomic/validate_command.py", "commands/validate_cmd/run.py",
            ],
        },
    ]

    trees = []
    for tmpl in templates:
        verified_lines = list(tmpl["lines"])
        for check in tmpl.get("check_files", []):
            if not (pkg_root / check).exists():
                verified_lines.append(f"  (MISSING: {check})")
        trees.append({"title": tmpl["title"], "lines": verified_lines})
    return trees


def _vm_command_summary(pkg_root: Path) -> list[tuple[str, str, str, str]]:
    """Generate command summary rows for VM Builder."""
    entries = [
        ("init", "init_cmd/run.py", "InitService", "BWS"),
        ("hypervisor bootstrap", "hypervisor_cmd/run.py", "HypervisorService", "BWS, Tailscale API, GitHub API, Jinja2"),
        ("vm create", "vm_cmd/create.py", "VmService", "BWS, ssh-keygen"),
        ("vm list", "vm_cmd/list.py", "VmService", "BWS"),
        ("vm delete", "vm_cmd/delete.py", "VmService", "BWS"),
        ("vm deploy", "vm_cmd/deploy.py", "VmService", "BWS, gh CLI"),
        ("validate", "validate_cmd/run.py", "VmService", "BWS"),
        ("registry generate", "(direct)", "RegistryGenerator", "File I/O"),
    ]
    rows = []
    for cmd, handler, service, io in entries:
        rows.append((cmd, handler, service, io))
    return rows


# ---------------------------------------------------------------------------
# Section 3: MCP Tool Map (IDI) / API Route Map (VM Builder)
# ---------------------------------------------------------------------------

def generate_mcp_tool_map(pkg_root: Path) -> str:
    """Generate Section 3 for IDI: MCP Tool Map."""
    lines = ["## 3. MCP Tool Map", "",
             "All 5 tools registered on the FastMCP server, traced to their implementation files.", ""]

    server_file = pkg_root / "mcp" / "server.py"
    tree = _parse_file(server_file) if server_file.exists() else None

    # Server setup tree
    lines.append("### Server Setup (mcp/server.py)")
    lines.append("")
    lines.append("```python")
    lines.append('FastMCP("idi", transport="stdio")')

    tools = _extract_mcp_tools(tree, pkg_root) if tree else []
    for tool in tools:
        lines.append(f"├── @mcp.tool() {tool['name']:<10} → mcp/tools/{tool['impl_file']}")
    lines.append("```")
    lines.append("")

    # Per-tool details
    for tool in tools:
        lines.append(f"### {tool['name']} — {tool['summary']}")
        lines.append("")

        # Parameter table
        if tool["params"]:
            lines.append("| Parameter | Type | Default | Description |")
            lines.append("|---|---|---|---|")
            for p in tool["params"]:
                ptype = p.get("type", "str")
                default = p.get("default", "required")
                desc = p.get("desc", "")
                lines.append(f"| `{p['name']}` | {ptype} | {default} | {desc} |")
            lines.append("")

        # Fix 2: Resolve mode table
        if tool["name"] == "resolve":
            modes = _extract_resolve_modes(server_file)
            if modes:
                lines.append("**Resolution modes:**")
                lines.append("")
                lines.append("| Mode | Parameters | Behavior |")
                lines.append("|---|---|---|")
                for mode in modes:
                    lines.append(f"| {mode[0]} | {mode[1]} | {mode[2]} |")
                lines.append("")

            # Fix 5: Session constants
            session_consts = _extract_session_constants(pkg_root / "mcp" / "tools" / "resolve" / "session.py")
            if session_consts:
                lines.append("**Session constants:**")
                for name, value in session_consts:
                    lines.append(f"- `{name} = {value}`")
                lines.append("")

        # Fix 3: Returns block
        if tool.get("returns"):
            lines.append(f"**Returns:** {tool['returns']}")
            lines.append("")

        # Cypher queries from implementation file (Fix 4: scan directory for resolve/)
        impl_path = pkg_root / "mcp" / "tools" / tool["impl_file"]
        if tool["name"] == "resolve":
            resolve_dir = pkg_root / "mcp" / "tools" / "resolve"
            queries = _grep_cypher_queries_dir(resolve_dir) if resolve_dir.exists() else []
        else:
            queries = _grep_cypher_queries(impl_path) if impl_path.exists() else []
        if queries:
            lines.append("**Neo4j queries:**")
            for q in queries:
                lines.append(f"- `{q}`")
            lines.append("")

    return "\n".join(lines)


def _extract_mcp_tools(tree: ast.Module | None, pkg_root: Path) -> list[dict]:
    """Extract MCP tool definitions from server.py AST."""
    if not tree:
        return []

    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        # Check for @mcp.tool() decorator
        is_tool = False
        for dec_info in _get_decorator_info(node):
            if dec_info.get("name") == "mcp" and dec_info.get("attr") == "tool":
                is_tool = True
                break
        if not is_tool:
            continue

        doc = ast.get_docstring(node) or ""
        summary = doc.split("\n")[0].rstrip(".") if doc else node.name
        params = _get_func_params(node)

        # Find the delegate call to determine implementation file
        impl_file = f"{node.name}.py"
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                # Map function call to known implementation file
                func_name = child.func.id
                impl_map = {
                    "query_skills": "query.py",
                    "get_skill_context": "context.py",
                    "resolve_plan": "resolve/plan.py",
                    "get_examples": "examples.py",
                    "record_workflow": "record.py",
                }
                if func_name in impl_map:
                    impl_file = impl_map[func_name]
                    break

        # Enrich params with descriptions from impl file's Args: block (Fix 1)
        impl_path = pkg_root / "mcp" / "tools" / impl_file
        impl_param_descs = _extract_impl_param_descriptions(impl_path) if impl_path.exists() else {}
        # Fallback to server.py docstring patterns
        server_param_descs = _extract_param_descriptions(doc)
        enriched_params = []
        for p in params:
            desc = impl_param_descs.get(p["name"], "") or server_param_descs.get(p["name"], "")
            enriched_params.append({
                "name": p["name"],
                "type": p.get("type", "str"),
                "default": p.get("default", "required"),
                "desc": desc,
            })

        # Extract Returns: from impl file (Fix 3)
        returns_text = _extract_impl_returns(impl_path) if impl_path.exists() else ""

        tools.append({
            "name": node.name,
            "summary": summary,
            "params": enriched_params,
            "impl_file": impl_file,
            "returns": returns_text,
        })

    return tools


def _parse_google_args(docstring: str) -> dict[str, str]:
    """Parse Google-style Args: block. Returns {param_name: description}."""
    descs: dict[str, str] = {}
    if not docstring:
        return descs
    in_args = False
    current_param: str | None = None
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped == "Args:":
            in_args = True
            continue
        if in_args:
            # End of Args block
            if stripped and not stripped[0].isspace() and stripped.endswith(":") and ":" not in stripped[:-1]:
                break
            if stripped.startswith("Returns:") or stripped.startswith("Raises:"):
                break
            # New param line: "    param_name: Description text" or "    param_name (type): Description"
            match = re.match(r"\s{4,}(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)", line)
            if match:
                current_param = match.group(1)
                descs[current_param] = match.group(2).strip()
            elif current_param and stripped and line.startswith("        "):
                # Continuation line
                descs[current_param] += " " + stripped
    return descs


def _parse_google_returns(docstring: str) -> str:
    """Parse Google-style Returns: block. Returns the description text."""
    if not docstring:
        return ""
    in_returns = False
    parts: list[str] = []
    for line in docstring.split("\n"):
        stripped = line.strip()
        if stripped == "Returns:":
            in_returns = True
            continue
        if in_returns:
            if stripped.startswith("Raises:") or stripped.startswith("Args:"):
                break
            if stripped and not stripped[0].isspace() and stripped.endswith(":") and ":" not in stripped[:-1]:
                break
            if stripped:
                parts.append(stripped)
            elif parts:
                break  # blank line after content ends the block
    return " ".join(parts)


def _extract_impl_param_descriptions(impl_path: Path) -> dict[str, str]:
    """Parse Args: block from impl file's main function docstring."""
    tree = _parse_file(impl_path)
    if not tree:
        return {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or ""
            return _parse_google_args(doc)
    return {}


def _extract_impl_returns(impl_path: Path) -> str:
    """Parse Returns: block from impl file's main function docstring."""
    tree = _parse_file(impl_path)
    if not tree:
        return ""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or ""
            return _parse_google_returns(doc)
    return ""


def _extract_param_descriptions(docstring: str) -> dict[str, str]:
    """Extract parameter descriptions from a docstring."""
    descs: dict[str, str] = {}
    if not docstring:
        return descs
    for line in docstring.split("\n"):
        line = line.strip()
        # Match patterns like "- skill_path: description" or ":param skill_path: description"
        match = re.match(r"[-:]\s*(?:param\s+)?(\w+)\s*[:—]\s*(.+)", line)
        if match:
            descs[match.group(1)] = match.group(2).strip()
    return descs


def _grep_cypher_queries(filepath: Path) -> list[str]:
    """Extract Cypher query patterns from a Python file using regex."""
    if not filepath.exists():
        return []
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []

    queries = []
    # Match MATCH/MERGE/CREATE patterns in strings
    for match in re.finditer(r'["\']+((?:MATCH|MERGE|CREATE)\s+\([^"\']{5,})', content):
        query = match.group(1).strip()
        # Truncate to first meaningful clause
        query = query.split("\\n")[0].split("\n")[0]
        if len(query) > 80:
            query = query[:77] + "..."
        if query not in queries:
            queries.append(query)
    return queries[:6]  # Cap at 6 queries


def _grep_cypher_queries_dir(dir_path: Path) -> list[str]:
    """Extract Cypher query patterns from all Python files in a directory."""
    all_queries: list[str] = []
    if not dir_path.exists():
        return all_queries
    for py_file in sorted(dir_path.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        for q in _grep_cypher_queries(py_file):
            if q not in all_queries:
                all_queries.append(q)
    return all_queries[:8]  # Cap at 8 queries for multi-file scan


def _extract_resolve_modes(server_file: Path) -> list[tuple[str, str, str]]:
    """Extract the 4 resolve modes from the resolve() docstring in server.py."""
    tree = _parse_file(server_file)
    if not tree:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "resolve":
            doc = ast.get_docstring(node) or ""
            return _parse_resolve_modes(doc)
    return []


def _parse_resolve_modes(docstring: str) -> list[tuple[str, str, str]]:
    """Parse the Four modes: block from the resolve docstring."""
    modes = []
    in_modes = False
    for line in docstring.split("\n"):
        stripped = line.strip()
        if "Four modes:" in stripped:
            in_modes = True
            continue
        if in_modes:
            if stripped.startswith("- "):
                # "- skill_path: Description text"
                match = re.match(r"-\s+(\w+)(?:\s+\+\s+(\w+))?\s*:\s*(.+)", stripped)
                if match:
                    mode = match.group(1)
                    extra = match.group(2)
                    desc = match.group(3).strip().rstrip(".")
                    if extra:
                        params = f"`{mode}` + `{extra}`"
                    else:
                        params = f"`{mode}`"
                    modes.append((mode, params, desc))
            elif stripped.startswith("Provide ") or (stripped and not stripped.startswith("-")):
                break
    return modes


def _extract_session_constants(session_file: Path) -> list[tuple[str, str]]:
    """Extract SESSION_* and MAX_* constants from session.py."""
    tree = _parse_file(session_file)
    if not tree:
        return []
    consts = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and (target.id.startswith("SESSION_") or target.id.startswith("MAX_")):
                    if isinstance(node.value, ast.Constant):
                        consts.append((target.id, repr(node.value.value)))
    return consts


def generate_api_route_map(pkg_root: Path) -> str:
    """Generate Section 3 for VM Builder: API Route Map."""
    lines = ["## 3. API Route Map", "",
             "All endpoints across route files, traced to their service and atomic parts.", ""]

    # Router registration order (from app.py AST)
    lines.append("### Router Registration Order (app.py)")
    lines.append("")
    lines.append("```python")
    registration_order = _detect_router_registration(pkg_root / "api" / "app.py")
    for i, (module_name, prefix) in enumerate(registration_order, 1):
        lines.append(f"{i}. {module_name}.router{' ' * max(1, 25 - len(module_name))}# {prefix}")
    lines.append("```")
    lines.append("")

    # Middleware
    lines.append("### Middleware Stack")
    lines.append("")
    lines.append("- `CORSMiddleware` — Allows `http://localhost:5173`, all methods/headers")
    lines.append("- `AuditMiddleware` — Logs all API requests, redacts secrets, skips health/docs/static")
    lines.append("")

    # Fix 10: Exception Handler, SPA Serving, Lifespan subsections
    app_file = pkg_root / "api" / "app.py"
    if app_file.exists():
        app_content = app_file.read_text(encoding="utf-8")

        # Exception handler
        if "@app.exception_handler" in app_content or "VmBuilderError" in app_content:
            lines.append("### Exception Handling")
            lines.append("")
            lines.append("- `VmBuilderError` → JSON 400 response with error details")
            lines.append("- Unhandled exceptions → JSON 500 with request ID for correlation")
            lines.append("")

        # SPA serving
        if "StaticFiles" in app_content or "_SPA_CANDIDATES" in app_content:
            lines.append("### SPA Serving")
            lines.append("")
            lines.append("- `_SPA_CANDIDATES`: probes `vm-builder-web/dist` (dev) and `/app/web/dist` (container)")
            lines.append("- `StaticFiles` mount at `/` for static assets")
            lines.append("- Fallback `index.html` for client-side routing")
            lines.append("")

        # Lifespan events
        lifespan_steps = _extract_lifespan_steps(app_file)
        if lifespan_steps:
            lines.append("### Lifespan Events (startup)")
            lines.append("")
            for step in lifespan_steps:
                lines.append(f"- {step}")
            lines.append("")

    # Per-route-file tables
    routes_dir = pkg_root / "api" / "routes"
    if routes_dir.exists():
        for route_file in sorted(routes_dir.glob("*.py")):
            if route_file.name == "__init__.py":
                continue
            routes = _extract_routes(route_file)
            if not routes:
                continue

            lines.append(f"### {route_file.stem}.py")
            lines.append("")
            lines.append("| Method | Path | Handler | Service | Chain |")
            lines.append("|---|---|---|---|---|")
            for r in routes:
                svc = r.get("service", "")
                chain = r.get("chain", "")
                lines.append(f"| {r['method']} | `{r['full_path']}` | `{r['handler']}` | {svc} | {chain} |")
            lines.append("")

    # Dependency Injection table
    lines.append("### Dependency Injection (deps.py)")
    lines.append("")
    di_entries = _extract_di_functions(pkg_root / "api" / "deps.py")
    if di_entries:
        lines.append("All injectors use `@lru_cache` for singleton services:")
        lines.append("")
        lines.append("| Injector | Service | Wired Dependencies |")
        lines.append("|---|---|---|")
        for name, return_type, wired_deps in di_entries:
            lines.append(f"| `{name}()` | `{return_type}` | {wired_deps} |")

    return "\n".join(lines)


def _detect_router_registration(app_file: Path) -> list[tuple[str, str]]:
    """Detect app.include_router() calls from app.py."""
    tree = _parse_file(app_file)
    if not tree:
        return []

    # Also need the prefixes from each route module
    routes_dir = app_file.parent / "routes"
    module_prefixes: dict[str, str] = {}
    if routes_dir.exists():
        for rf in sorted(routes_dir.glob("*.py")):
            if rf.name == "__init__.py":
                continue
            rt = _parse_file(rf)
            if rt:
                prefix = _get_router_prefix(rt)
                module_prefixes[rf.stem] = prefix or "/api/v1"

    registrations = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"):
            # Extract the module name from the argument
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                    mod_name = arg.value.id
                    prefix = module_prefixes.get(mod_name, "")
                    registrations.append((mod_name, prefix))
    return registrations


def _extract_routes(route_file: Path) -> list[dict[str, str]]:
    """Extract HTTP routes from a FastAPI route file."""
    tree = _parse_file(route_file)
    if not tree:
        return []

    prefix = _get_router_prefix(tree)
    routes = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec_info in _get_decorator_info(node):
            attr = dec_info.get("attr", "")
            name = dec_info.get("name", "")
            if name == "router" and attr in ("get", "post", "put", "delete", "patch"):
                args = dec_info.get("args", [])
                path = args[0] if args else "/"
                full_path = prefix + path
                service, method = _extract_route_service(node)
                chain = f"{service}.{method}()" if service and method else ""
                routes.append({
                    "method": attr.upper(),
                    "full_path": full_path,
                    "handler": node.name,
                    "service": service,
                    "chain": chain,
                })

    return routes


def _extract_route_service(node: ast.AsyncFunctionDef | ast.FunctionDef) -> tuple[str, str]:
    """Extract service name and method from route handler body.

    Detects patterns like:
      svc = get_X_service()
      asyncio.to_thread(svc.method, ...)
    """
    service = ""
    method = ""
    for child in ast.walk(node):
        # Detect: svc = get_X_service() or Depends(get_X_service)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            fname = child.func.id
            if fname.startswith("get_") and fname.endswith("_service"):
                service_snake = fname.replace("get_", "").replace("_service", "")
                service = "".join(w.capitalize() for w in service_snake.split("_")) + "Service"
        # Detect: asyncio.to_thread(svc.method, ...)
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr == "to_thread":
                if child.args and isinstance(child.args[0], ast.Attribute):
                    method = child.args[0].attr
    return service, method


def _extract_lifespan_steps(app_file: Path) -> list[str]:
    """Extract lifespan startup steps from app.py's lifespan() docstring."""
    tree = _parse_file(app_file)
    if not tree:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            doc = ast.get_docstring(node) or ""
            steps = []
            for line in doc.split("\n"):
                stripped = line.strip()
                # Match numbered steps: "1. Load config from BWS..."
                match = re.match(r"\d+\.\s+(.+)", stripped)
                if match:
                    steps.append(match.group(1).rstrip(".") + ".")
            return steps
    return []


def _extract_di_functions(deps_file: Path) -> list[tuple[str, str, str]]:
    """Extract @lru_cache DI functions from deps.py with wired deps."""
    tree = _parse_file(deps_file)
    if not tree:
        return []

    entries = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        # Check for @lru_cache decorator
        has_cache = False
        for dec_info in _get_decorator_info(node):
            if dec_info.get("name") == "lru_cache":
                has_cache = True
                break
        # Also check bare name decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "lru_cache":
                has_cache = True
                break

        if not has_cache:
            continue

        # Get return type
        return_type = ""
        if node.returns:
            return_type = ast.unparse(node.returns)

        # Fix 11: Extract wired dependencies (calls to other get_* functions)
        wired_deps = _extract_di_wired_deps(node)
        deps_str = ", ".join(wired_deps)
        entries.append((node.name, return_type, deps_str))

    return entries


def _extract_di_wired_deps(node: ast.FunctionDef) -> list[str]:
    """Find get_*() calls within a DI function body."""
    deps = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            if child.func.id.startswith("get_") and child.func.id != node.name:
                dep = child.func.id + "()"
                if dep not in deps:
                    deps.append(dep)
    return deps


# ---------------------------------------------------------------------------
# Section 4: External Dependency Flow
# ---------------------------------------------------------------------------

def generate_external_deps_idi(pkg_root: Path, cgc: Any) -> str:
    """Generate Section 4 for IDI package."""
    lines = ["## 4. External Dependency Flow", "",
             "Which modules call which external systems, traced to exact files.", ""]

    # 4.1 OpenAPI Specs
    lines.append("### 4.1 OpenAPI Specifications")
    lines.append("")
    lines.append("**Processed by:** `generation/spec_loader.py` (with built-in `$ref` resolver)")
    lines.append("")
    spec_callers = [
        ("Skill generation", "generation/spec_loader.py"),
        ("Spec download", "generation/download_specs.py"),
        ("CRD schemas", "generation/crd_schemas.py"),
    ]
    lines.append("| Caller | File |")
    lines.append("|---|---|")
    for caller, file in spec_callers:
        if (pkg_root / file).exists():
            lines.append(f"| {caller} | `{file}` |")
    lines.append("")

    # 4.2 HTTP
    lines.append("### 4.2 HTTP (httpx)")
    lines.append("")
    lines.append("**Used by:** `generation/download_specs.py` (fetching OpenAPI specs)")
    lines.append("")
    httpx_callers = _detect_httpx_callers(pkg_root, "")
    if httpx_callers:
        lines.append("| Module | File |")
        lines.append("|---|---|")
        for module, file in httpx_callers:
            lines.append(f"| {module} | `{file}` |")
        lines.append("")

    # 4.3 File I/O
    lines.append("### 4.3 File I/O")
    lines.append("")
    file_io = [
        ("Generation", "catalog/skills/api/{service}/{resource}/", "Write JSON skill artifacts"),
        ("Generation", "specs/", "Read OpenAPI spec files"),
        ("Common", "schemas/", "Read JSON Schema files for validation"),
    ]
    lines.append("| Module | Path | Operation |")
    lines.append("|---|---|---|")
    for module, path, op in file_io:
        lines.append(f"| {module} | `{path}` | {op} |")
    lines.append("")

    # Key Dependency Chains
    lines.append("### Key Dependency Chains")
    lines.append("")

    chains = [
        ("Skill Generation (longest chain):", [
            "CLI → load OpenAPI spec (HTTP/file)",
            "  → extract operations from paths",
            "  → build compound resource names (disambiguation)",
            "  → extract fields from request/response schemas",
            "  → detect dependencies via adapter pipeline",
            "  → resolve polymorphic targets",
            "  → canonicalize fact URIs",
            "  → write JSON artifacts (manifest + operations + fields)",
        ]),
    ]

    for title, chain_lines in chains:
        lines.append(f"**{title}**")
        lines.append("```")
        for cl in chain_lines:
            lines.append(cl)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def generate_external_deps_vm(pkg_root: Path, cgc: Any) -> str:
    """Generate Section 4 for VM Builder package."""
    lines = ["## 4. External Dependency Flow", "",
             "Which services call which external systems, traced to exact files.", ""]

    # 4.1 BWS
    lines.append("### 4.1 BWS (Bitwarden Secrets Manager)")
    lines.append("")
    lines.append("**Call method:** `bws` CLI wrapper via subprocess")
    lines.append(f"**Facade:** `vm_builder/bws.py` → `bws_parts/*.py`")
    lines.append("")

    bws_callers = _detect_bws_callers(pkg_root)
    if bws_callers:
        lines.append("| Caller Service | Key Paths | Operations |")
        lines.append("|---|---|---|")
        for service, files, ops in bws_callers:
            paths = ", ".join(f"`{f}`" for f in files[:3])
            if len(files) > 3:
                paths += f" + {len(files) - 3} more"
            ops_str = ", ".join(f"`{o}`" for o in sorted(ops)) if ops else ""
            lines.append(f"| `{service}` | {paths} | {ops_str} |")
        lines.append("")

    # 4.2 GitHub API
    lines.append("### 4.2 GitHub API (httpx)")
    lines.append("")
    lines.append("**Base URL:** `https://api.github.com`")
    lines.append("")
    gh_api_callers = _detect_httpx_callers(pkg_root, "api.github.com")
    if gh_api_callers:
        lines.append("| File | Operations |")
        lines.append("|---|---|")
        for file, ops in gh_api_callers:
            lines.append(f"| `{file}` | {ops} |")
        lines.append("")

    # 4.3 GitHub CLI
    lines.append("### 4.3 GitHub CLI (subprocess)")
    lines.append("")
    gh_cli_callers = _detect_gh_cli_callers(pkg_root)
    if gh_cli_callers:
        lines.append("| File | Command |")
        lines.append("|---|---|")
        for file, cmd in gh_cli_callers:
            lines.append(f"| `{file}` | `{cmd}` |")
        lines.append("")

    # 4.4 Tailscale API
    lines.append("### 4.4 Tailscale API (httpx)")
    lines.append("")
    lines.append("**Base URL:** `https://api.tailscale.com/api/v2`")
    lines.append("")
    ts_callers = _detect_httpx_callers(pkg_root, "api.tailscale.com")
    if ts_callers:
        lines.append("| File | Operations |")
        lines.append("|---|---|")
        for file, ops in ts_callers:
            lines.append(f"| `{file}` | {ops} |")
        lines.append("")

    # 4.5 SSH
    lines.append("### 4.5 SSH (subprocess over Tailscale)")
    lines.append("")
    ssh_file = pkg_root / "core" / "storage_service_parts" / "ssh_cmd.py"
    if ssh_file.exists():
        lines.append(f"**File:** `core/storage_service_parts/ssh_cmd.py`")
        lines.append("")
        ssh_callers = [
            ("detect_mounts.py", "`mount` command"),
            ("browse_path.py", "`ls -la` command"),
            ("verify_nfs.py", "NFS mount test"),
            ("verify_smb.py", "smbclient test"),
        ]
        lines.append("| Caller | Purpose |")
        lines.append("|---|---|")
        for caller, purpose in ssh_callers:
            if (pkg_root / "core" / "storage_service_parts" / caller).exists():
                lines.append(f"| `storage_service_parts/{caller}` | {purpose} |")
        lines.append("")

    # 4.6 Jinja2
    lines.append("### 4.6 Jinja2 Templates")
    lines.append("")
    jinja_callers = _detect_jinja_callers(pkg_root)
    if jinja_callers:
        lines.append("| File | Usage |")
        lines.append("|---|---|")
        for file, usage in jinja_callers:
            lines.append(f"| `{file}` | {usage} |")
        lines.append("")

    # Fix 14: File I/O paths
    lines.append("### 4.7 File I/O Paths")
    lines.append("")
    file_io_paths = [
        ("`~/.vm-builder/audit/`", "Audit log files"),
        ("`/data/repo/`", "Cloned enterprise repo (container)"),
        ("`/data/registry.json`", "Fallback registry (container)"),
        ("REGISTRY_PATH env", "Registry JSON (overridable)"),
        ("TEMPLATES_DIR env", "Templates directory for J2 scanning"),
    ]
    lines.append("| Path | Purpose |")
    lines.append("|---|---|")
    for path, purpose in file_io_paths:
        lines.append(f"| {path} | {purpose} |")
    lines.append("")

    # Fix 14: GitHub Actions workflows
    workflows_dir = ROOT / ".github" / "workflows"
    if workflows_dir.exists():
        lines.append("### 4.8 GitHub Actions Workflows")
        lines.append("")
        wf_entries = _detect_github_workflows(workflows_dir)
        if wf_entries:
            lines.append("| Workflow File | Name |")
            lines.append("|---|---|")
            for fname, wf_name in wf_entries:
                lines.append(f"| `{fname}` | {wf_name} |")
            lines.append("")

    # Key Dependency Chains
    lines.append("### Key Dependency Chains")
    lines.append("")

    chains = [
        ("Hypervisor Bootstrap (longest chain):", [
            "API request → HypervisorService.generate_bootstrap_script()",
            "  → BWS: Read Tailscale OAuth credentials",
            "  → Tailscale API: OAuth token exchange",
            "  → Tailscale API: Create device auth key",
            "  → BWS: Read GitHub PAT",
            "  → GitHub API: Create runner registration token",
            "  → BWS: Create hypervisor inventory entry",
            "  → Jinja2: Render bootstrap shell script",
        ]),
        ("VM Deployment:", [
            "API request → VmService.deploy_vm()",
            "  → BWS: Read VM inventory",
            "  → gh CLI: Trigger provision workflow",
            "  → gh CLI: Fetch latest run status",
        ]),
        ("App Installation:", [
            "API request → AppInstallService.install_apps()",
            "  → Registry: Resolve dependency order",
            "  → gh CLI: Trigger phase3-install-app.yml (per app)",
            "  → gh CLI: Trigger phase4-configure-app.yml (per app)",
            "  → BWS: Update inventory app state",
        ]),
        ("Health Check:", [
            "API request → HealthService.get_vm_health()",
            "  → BWS: Read Tailscale OAuth credentials",
            "  → Tailscale API: OAuth token exchange",
            "  → Tailscale API: List all devices",
            "  → VmService: List VMs from BWS",
            "  → Match devices to VMs by hostname",
        ]),
    ]

    for title, chain_lines in chains:
        lines.append(f"**{title}**")
        lines.append("```")
        for cl in chain_lines:
            lines.append(cl)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _detect_bws_callers(pkg_root: Path) -> list[tuple[str, list[str], set[str]]]:
    """Detect which service _parts/ directories call bws functions."""
    callers = []
    core_dir = pkg_root / "core"
    if not core_dir.exists():
        return callers

    for parts_dir in sorted(core_dir.iterdir()):
        if not parts_dir.is_dir() or not parts_dir.name.endswith("_parts"):
            continue

        service_name = parts_dir.name.replace("_parts", "")
        # Convert snake_case to CamelCase
        service_class = "".join(w.capitalize() for w in service_name.split("_"))

        bws_files = []
        all_ops: set[str] = set()
        for py_file in sorted(parts_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            if re.search(r"bws\.\w+", content):
                rel = f"core/{parts_dir.name}/{py_file.name}"
                bws_files.append(rel)
                # Fix 15: Extract specific bws operations
                for m in re.finditer(r"bws\.(\w+)\s*\(", content):
                    all_ops.add(m.group(1))

        if bws_files:
            callers.append((service_class, bws_files, all_ops))

    return callers


def _detect_httpx_callers(pkg_root: Path, domain: str) -> list[tuple[str, str]]:
    """Detect files making httpx calls to a specific domain."""
    results = []
    for py_file in sorted(pkg_root.rglob("*.py")):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue

        if domain not in content and "httpx" not in content:
            continue

        # Look for httpx method calls
        ops = set()
        for match in re.finditer(r'httpx\.\w+\.?(get|post|put|delete|patch)\b', content):
            ops.add(match.group(1).upper())
        for match in re.finditer(r'\.(?:get|post|put|delete|patch)\s*\(', content):
            method = match.group(0).strip().split("(")[0].strip(".").upper()
            ops.add(method)

        # Fix 13: Extract API endpoint paths from f-strings and strings
        endpoints: list[str] = []
        for m in re.finditer(r'f?["\'](?:https?://[^"\']*?)?(/v\d+/[^"\'{} ]+)', content):
            ep = m.group(1)
            if ep not in endpoints:
                endpoints.append(ep)
        for m in re.finditer(r'f["\']([^"\']+/(?:repos|orgs|actions|runners|keys|devices|tailnet)[^"\']*)', content):
            ep = m.group(1)
            if ep not in endpoints:
                endpoints.append(ep)

        if domain in content:
            rel = str(py_file.relative_to(pkg_root)).replace("\\", "/")
            op_parts = []
            if ops:
                op_parts.append(", ".join(sorted(ops)))
            if endpoints:
                ep_list = ", ".join(f"`{e}`" for e in endpoints[:3])
                op_parts.append(ep_list)
            op_str = "; ".join(op_parts) if op_parts else "HTTP calls"
            results.append((rel, op_str))

    return results


def _detect_gh_cli_callers(pkg_root: Path) -> list[tuple[str, str]]:
    """Detect files that use the gh CLI via subprocess."""
    results = []
    for py_file in sorted(pkg_root.rglob("*.py")):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue

        if '"gh"' not in content and "'gh'" not in content:
            continue

        rel = str(py_file.relative_to(pkg_root)).replace("\\", "/")

        # Extract full gh commands (up to 4 subcommand parts)
        seen: set[str] = set()
        for match in re.finditer(
            r'["\']gh["\']\s*(?:,\s*["\'](\w+)["\'](?:\s*,\s*["\'](\w+)["\'](?:\s*,\s*["\'](\w+)["\'])?)?)?',
            content,
        ):
            parts = ["gh"]
            for g in match.groups():
                if g:
                    parts.append(g)
            cmd = " ".join(parts)
            if cmd != "gh" and cmd not in seen:
                seen.add(cmd)
                results.append((rel, cmd))

    return results


def _detect_jinja_callers(pkg_root: Path) -> list[tuple[str, str]]:
    """Detect files that use Jinja2 templates."""
    results = []
    for py_file in sorted(pkg_root.rglob("*.py")):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue

        rel = str(py_file.relative_to(pkg_root)).replace("\\", "/")

        if "jinja2" in content.lower() or "Template(" in content:
            if "Environment" in content or "Template(" in content:
                usage = "Template rendering"
            elif "find_undeclared_variables" in content:
                usage = "Variable discovery"
            else:
                usage = "Jinja2 usage"
            results.append((rel, usage))

    return results


def _detect_github_workflows(workflows_dir: Path) -> list[tuple[str, str]]:
    """Extract workflow file names and their 'name:' field."""
    results = []
    for wf_file in sorted(workflows_dir.glob("*.yml")):
        try:
            content = wf_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        name = wf_file.name
        wf_name = ""
        for line in content.split("\n")[:10]:
            m = re.match(r"^name:\s*(.+)", line)
            if m:
                wf_name = m.group(1).strip().strip("'\"")
                break
        results.append((name, wf_name or "(unnamed)"))
    return results


# ---------------------------------------------------------------------------
# Section 5: Architecture Patterns / Web Index
# ---------------------------------------------------------------------------

def generate_arch_patterns_idi(pkg_root: Path) -> str:
    """Generate Section 5 for IDI: Architectural Patterns."""
    lines = ["## 5. Architectural Patterns", ""]

    patterns = [
        {
            "title": "Two-Pass Skill Generation",
            "diagram": [
                "Pass 1 — Discovery:",
                "  OpenAPI spec → path_extractor → resource_namer",
                "  → register all skill paths in GeneratorContext",
                "",
                "Pass 2 — Emit:",
                "  For each operation:",
                "    → field_extractor (request + response schemas)",
                "    → adapters (detect API family quirks)",
                "    → dep_adapters (detect dependencies)",
                "    → polymorphic (resolve ambiguous targets)",
                "    → fact_model (canonicalize fact URIs)",
                "    → output_writer (write JSON)",
            ],
            "check_files": [
                "generation/path_extractor.py", "generation/resource_namer.py",
                "generation/field_extractor.py", "generation/output_writer.py",
                "generation/context.py",
            ],
        },
        {
            "title": "Path Canonicalization",
            "text": [
                "All operation paths use extensionless canonical form:",
                "- **Canonical:** `authentik/oauth2/create`",
                "- **Legacy .md form:** `authentik/oauth2/create.md` → automatically stripped",
                "- **Normalizer:** `idi.common.paths.normalize_op_path()`",
            ],
            "check_files": ["common/paths.py"],
        },
        {
            "title": "Fact Identity Model",
            "diagram": [
                "facts://service/resource#field",
                "  └── canonical form with alias resolution",
                "      id, pk, uuid, guid, uid → all canonicalize to \"id\"",
            ],
            "text": [
                "",
                "**Components:**",
                "- `generation/fact_model.py` — FactRef dataclass with canonical_field",
                "- `generation/fact_registry.py` — Maps facts to producing operations",
            ],
            "check_files": [
                "generation/fact_model.py", "generation/fact_registry.py",
            ],
        },
    ]

    for pat in patterns:
        # Skip patterns where no check_files exist
        existing = [f for f in pat.get("check_files", []) if (pkg_root / f).exists()]
        if not existing:
            continue

        lines.append(f"### {pat['title']}")
        lines.append("")

        if "diagram" in pat:
            lines.append("```")
            for dl in pat["diagram"]:
                lines.append(dl)
            lines.append("```")

        if "text" in pat:
            for tl in pat["text"]:
                lines.append(tl)

        # Verify referenced files
        missing = [f for f in pat.get("check_files", []) if not (pkg_root / f).exists()]
        if missing:
            lines.append("")
            for m in missing:
                lines.append(f"> (MISSING: `{m}`)")

        lines.append("")

    return "\n".join(lines)


def generate_arch_patterns_vm(pkg_root: Path) -> str:
    """Generate architectural patterns section for VM Builder."""
    lines = ["## Architectural Patterns", ""]

    # Detect _ModuleProxy + _wire() pattern
    proxy_files = _detect_module_proxy_pattern(pkg_root)
    lines.append("### _ModuleProxy + _wire() Pattern")
    lines.append("")
    lines.append("Every service facade uses this DI pattern for testability:")
    lines.append("")
    lines.append("```python")
    lines.append("class _ModuleProxy:")
    lines.append('    def __init__(self, target_name: str) -> None:')
    lines.append("        self._target_name = target_name")
    lines.append("    def __getattr__(self, attr: str):")
    lines.append("        return getattr(globals()[self._target_name], attr)")
    lines.append("")
    lines.append('def _wire(module, **deps: str) -> None:')
    lines.append("    for attr, target_name in deps.items():")
    lines.append("        setattr(module, attr, _ModuleProxy(target_name))")
    lines.append("```")
    lines.append("")

    if proxy_files:
        lines.append(f"**Used in {len(proxy_files)} facade files:** " +
                     ", ".join(f"`{f}`" for f in proxy_files[:5]))
        if len(proxy_files) > 5:
            lines.append(f"  + {len(proxy_files) - 5} more")
    lines.append("")

    # Fix 18: Extract a concrete _wire() example from a facade file
    wire_examples = _extract_wire_examples(pkg_root)
    if wire_examples:
        lines.append("**Usage examples:**")
        lines.append("")
        lines.append("```python")
        for ex_line in wire_examples:
            lines.append(ex_line)
        lines.append("```")
        lines.append("")

    # Detect Service Facade pattern
    facades = _detect_service_facades(pkg_root)
    lines.append("### Service Facade Pattern")
    lines.append("")
    lines.append("Each service: 1 facade file + N atomic parts files.")
    lines.append("")
    if facades:
        lines.append("| Facade | Parts Dir | Parts Count |")
        lines.append("|---|---|---|")
        for facade, parts_dir, count in facades:
            lines.append(f"| `{facade}` | `{parts_dir}/` | {count} |")
    lines.append("")

    return "\n".join(lines)


def _detect_module_proxy_pattern(pkg_root: Path) -> list[str]:
    """Find files containing _ModuleProxy class or _wire() function."""
    results = []
    core_dir = pkg_root / "core"
    if not core_dir.exists():
        return results

    for py_file in sorted(core_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if "_ModuleProxy" in content or "def _wire(" in content:
            results.append(f"core/{py_file.name}")

    return results


def _extract_wire_examples(pkg_root: Path) -> list[str]:
    """Find _wire() calls in facade files and extract as concrete examples."""
    core_dir = pkg_root / "core"
    if not core_dir.exists():
        return []

    examples: list[str] = []
    for py_file in sorted(core_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        tree = _parse_file(py_file)
        if not tree:
            continue

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Expr):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            if not (isinstance(call.func, ast.Name) and call.func.id == "_wire"):
                continue

            # Extract: _wire(module_var, key="value", ...)
            parts = []
            if call.args:
                for arg in call.args:
                    if isinstance(arg, ast.Name):
                        parts.append(arg.id)
            kwargs = []
            for kw in call.keywords:
                if kw.arg and isinstance(kw.value, ast.Constant):
                    kwargs.append(f'{kw.arg}="{kw.value.value}"')

            if parts or kwargs:
                line = f"_wire({', '.join(parts)}"
                if kwargs:
                    if parts:
                        line += ", "
                    line += ", ".join(kwargs)
                line += ")"
                source = f"  # from core/{py_file.name}"
                examples.append(line + source)

        if len(examples) >= 3:
            break

    return examples


def _detect_service_facades(pkg_root: Path) -> list[tuple[str, str, int]]:
    """Detect facade files that have corresponding _parts/ directories."""
    core_dir = pkg_root / "core"
    if not core_dir.exists():
        return []

    facades = []
    for py_file in sorted(core_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        stem = py_file.stem
        parts_dir = core_dir / f"{stem}_parts"
        if parts_dir.is_dir():
            parts_count = len(list(parts_dir.glob("*.py"))) - 1  # exclude __init__.py
            facades.append((f"core/{py_file.name}", f"core/{stem}_parts", max(0, parts_count)))

    return facades


def generate_web_index(web_src: Path) -> str:
    """Generate Section 5 for VM Builder: Web Application Module Index."""
    lines = ["## 5. Web Application Module Index", ""]

    if not web_src.exists():
        lines.append("(Web source directory not found)")
        return "\n".join(lines)

    # Collect all .ts and .tsx files
    ts_files = sorted(
        list(web_src.rglob("*.ts")) + list(web_src.rglob("*.tsx"))
    )
    total = len(ts_files)
    lines.append(f"{total} TypeScript/TSX files in `vm-builder/vm-builder-web/src/`. "
                 "React SPA with Vite + TypeScript + Tailwind CSS + TanStack Query.")
    lines.append("")

    # Group by directory
    groups: dict[str, list[tuple[str, str]]] = {}
    for f in ts_files:
        rel = str(f.relative_to(web_src)).replace("\\", "/")
        dir_path = str(f.parent.relative_to(web_src)).replace("\\", "/")
        if dir_path == ".":
            dir_path = ""

        desc = _extract_ts_description(f)
        groups.setdefault(dir_path, []).append((rel, desc))

    # Define display order for known directories
    dir_order = [
        ("", "Entry Points"),
        ("api", "API Layer"),
        ("pages", "Pages — Top-Level"),
        ("pages/vm-create", "Pages — vm-create/"),
        ("pages/vm-detail", "Pages — vm-detail/"),
        ("pages/vm-list", "Pages — vm-list/"),
        ("pages/init-secrets", "Pages — init-secrets/"),
        ("components", "Components — Top-Level"),
        ("components/app-selector", "Components — app-selector/"),
        ("components/storage-verifier", "Components — storage-verifier/"),
        ("components/sso-toggle-list", "Components — sso-toggle-list/"),
        ("components/gcp-config-panel", "Components — gcp-config-panel/"),
    ]

    subsection = 0
    stats: list[tuple[str, int]] = []
    seen_dirs: set[str] = set()

    for dir_path, title in dir_order:
        entries = groups.get(dir_path, [])
        if not entries:
            continue

        seen_dirs.add(dir_path)
        subsection += 1
        count = len(entries)
        noun = "file" if count == 1 else "files"
        lines.append(f"### 5.{subsection} {title} ({count} {noun})")
        lines.append("")
        lines.append("```")

        max_path = max(len(rel) for rel, _ in entries)
        pad = max_path + 1
        for rel, desc in entries:
            fname = rel.split("/")[-1]
            lines.append(f"{_pad_to(fname, pad)}— {desc}")
        lines.append("```")
        lines.append("")
        stats.append((title, count))

    # Any remaining directories not in the ordered list
    for dir_path in sorted(groups.keys()):
        if dir_path in seen_dirs:
            continue
        entries = groups[dir_path]
        seen_dirs.add(dir_path)
        subsection += 1
        count = len(entries)
        noun = "file" if count == 1 else "files"
        label = dir_path or "Other"
        lines.append(f"### 5.{subsection} {label} ({count} {noun})")
        lines.append("")
        lines.append("```")
        max_path = max(len(rel) for rel, _ in entries)
        pad = max_path + 1
        for rel, desc in entries:
            fname = rel.split("/")[-1]
            lines.append(f"{_pad_to(fname, pad)}— {desc}")
        lines.append("```")
        lines.append("")
        stats.append((label, count))

    # Summary table
    subsection += 1
    lines.append(f"### 5.{subsection} Web Summary")
    lines.append("")
    lines.append("| Area | Files |")
    lines.append("| --- | --- |")
    for name, count in stats:
        lines.append(f"| {name} | {count} |")
    lines.append(f"| **Total** | **{total}** |")

    return "\n".join(lines)


def _extract_ts_description(filepath: Path) -> str:
    """Extract description from a TypeScript file.

    Checks for first-line // comment or JSDoc @description.
    Falls back to export-based inference, then (no description).
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return "(read error)"

    for line in content.split("\n")[:5]:
        line = line.strip()
        # // Description comment
        if line.startswith("//") and not line.startswith("///"):
            desc = line.lstrip("/").strip()
            if desc and not desc.startswith("@") and len(desc) > 5:
                return desc + ("." if not desc.endswith(".") else "")
        # /** ... */ JSDoc on first line
        if line.startswith("/**"):
            desc = line.replace("/**", "").replace("*/", "").strip()
            if desc and len(desc) > 5:
                return desc + ("." if not desc.endswith(".") else "")

    # Fix 12: Infer from exports
    for line in content.split("\n"):
        # export default function ComponentName
        m = re.match(r"export\s+default\s+function\s+(\w+)", line)
        if m:
            return f"React component: {m.group(1)}."

        # export function useXxx (hooks)
        m = re.match(r"export\s+function\s+(use\w+)", line)
        if m:
            return f"Hook: {m.group(1)}."

        # export const XxxContext = createContext
        m = re.match(r"export\s+const\s+(\w+Context)\s*=\s*createContext", line)
        if m:
            return f"Context provider: {m.group(1)}."

        # export const Xxx = () => or export const Xxx: React.FC
        m = re.match(r"export\s+(?:default\s+)?(?:const|function)\s+(\w+)", line)
        if m and m.group(1)[0].isupper() and not m.group(1).startswith("use"):
            return f"Component: {m.group(1)}."

    # Check for type/interface exports
    has_types = False
    for line in content.split("\n"):
        if re.match(r"export\s+(?:type|interface)\s+\w+", line):
            has_types = True
            break
    if has_types:
        return "Type definitions."

    # Known file descriptions for common patterns
    stem = filepath.stem
    _TS_KNOWN = {
        "main": "Application entry point.",
        "App": "Root application component.",
        "vite-env": "Vite environment type declarations.",
        "index": "Module barrel export.",
    }
    if stem in _TS_KNOWN:
        return _TS_KNOWN[stem]

    return "(no description)"


# ---------------------------------------------------------------------------
# Symbol Index
# ---------------------------------------------------------------------------

# Directories containing "public surface" files to index for symbols
_IDI_SYMBOL_DIRS: list[str] = [
    "generation",
    "generation/adapters",
    "generation/dep_adapters",
    "generation/crd",
    "enrichment",
    "common",
]

_VM_SYMBOL_DIRS: list[str] = [
    "core",       # facades only (skip _parts/)
    "api/routes",
    "api",        # deps.py, app.py
    "cli_atomic",
    "commands",
]


def _collect_symbol_files(
    pkg_name: str, pkg_root: Path, symbol_dirs: list[str],
) -> list[Path]:
    """Recursively collect Python files to scan for symbols.

    Uses rglob so nested directories (e.g. mcp/tools/resolve/) are included.
    Deduplicates across overlapping dirs (e.g. mcp/tools ⊃ mcp/tools/resolve).
    Skips __init__.py, _parts/ directories (for vm_builder/core), and ignored dirs.
    """
    seen: set[Path] = set()
    for sdir in symbol_dirs:
        dir_path = pkg_root / sdir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file in seen:
                continue
            if py_file.name == "__init__.py":
                continue
            if _is_ignored(py_file.relative_to(pkg_root)):
                continue
            # For vm_builder/core, skip _parts/ directories
            if pkg_name == "vm_builder" and sdir == "core":
                rel_parts = py_file.relative_to(dir_path).parts
                if any("_parts" in p for p in rel_parts[:-1]):
                    continue
            seen.add(py_file)
    return sorted(seen, key=lambda p: str(p.relative_to(pkg_root)))


def _extract_public_symbols(filepath: Path) -> list[tuple[str, str, int, int]]:
    """Extract public class and function names from a Python file.

    Returns list of (symbol_name, kind, line_start, line_end).
    Handles facade-pattern class-level attribute assignments.
    """
    tree = _parse_file(filepath)
    if not tree:
        return []
    symbols: list[tuple[str, str, int, int]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            symbols.append((node.name, "class", node.lineno, node.end_lineno or node.lineno))
            # Methods + facade delegates
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not child.name.startswith("_"):
                        symbols.append((
                            f"{node.name}.{child.name}", "method",
                            child.lineno, child.end_lineno or child.lineno,
                        ))
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and not target.id.startswith("_"):
                            symbols.append((
                                f"{node.name}.{target.id}", "attribute",
                                child.lineno, child.lineno,
                            ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                symbols.append((node.name, "function", node.lineno, node.end_lineno or node.lineno))
    return symbols


def generate_symbol_index(pkg_name: str, pkg_root: Path) -> str:
    """Generate a symbol → file reverse index for public surface files."""
    symbol_dirs = _IDI_SYMBOL_DIRS if pkg_name == "idi" else _VM_SYMBOL_DIRS

    # Collect all (symbol, file, kind, line_start, line_end) tuples
    all_symbols: list[tuple[str, str, str, int, int]] = []

    for py_file in _collect_symbol_files(pkg_name, pkg_root, symbol_dirs):
        rel = _rel(py_file, pkg_root)
        for sym_name, kind, line_start, line_end in _extract_public_symbols(py_file):
            all_symbols.append((sym_name, rel, kind, line_start, line_end))

    if not all_symbols:
        return ""

    # Deterministic order: file, kind, symbol name
    all_symbols.sort(key=lambda x: (x[1], x[2], x[0].lower()))

    lines = ["### Symbol Index", ""]
    lines.append(f"{len(all_symbols)} public symbols from {len(symbol_dirs)} surface directories.")
    lines.append("")
    lines.append("| Symbol | File | Kind | Lines |")
    lines.append("|---|---|---|---|")
    for sym, filepath, kind, lstart, lend in all_symbols:
        if lstart == lend:
            loc = f"L{lstart}"
        else:
            loc = f"L{lstart}-{lend}"
        lines.append(f"| `{sym}` | `{filepath}` | {kind} | {loc} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Consistency validation
# ---------------------------------------------------------------------------

def _resolve_ref_path(ref: str, pkg_root: Path, web_src: Path | None) -> bool:
    """Try to resolve a referenced path to an existing file.

    Tries multiple strategies: direct, common parent prefixes, web source, project root.
    """
    # Direct match
    if (pkg_root / ref).exists():
        return True
    # Strip package prefix (e.g. vm_builder/bws.py → bws.py)
    pkg_name = pkg_root.name
    if ref.startswith(pkg_name + "/"):
        stripped = ref[len(pkg_name) + 1:]
        if (pkg_root / stripped).exists():
            return True
    # Try common parent prefixes for abbreviated paths
    # e.g., init_cmd/run.py → commands/init_cmd/run.py
    # e.g., storage_service_parts/detect_mounts.py → core/storage_service_parts/detect_mounts.py
    common_prefixes = ["commands", "core", "generation", "enrichment", "common"]
    for prefix in common_prefixes:
        if (pkg_root / prefix / ref).exists():
            return True
    # Web source for TS/TSX files
    if web_src and (ref.endswith(".ts") or ref.endswith(".tsx")):
        if (web_src / ref).exists():
            return True
    # Project root for cross-package refs
    if (ROOT / ref).exists():
        return True
    return False


def _validate_consistency(
    content: str,
    pkg_root: Path,
    web_src: Path | None,
    all_module_paths: set[str] | None = None,
    symbol_entries: list[tuple[str, str]] | None = None,
    index_data: dict[str, Any] | None = None,
) -> list[str]:
    """Validate generated index content for internal consistency.

    Checks performed:
    1. All backtick-referenced file paths (outside code blocks) exist on disk.
    2. Summary Statistics counts match the number of items actually listed.
    3. No duplicate symbol names in the Symbol Index.
    4. Every .py file in Entry Point Map sections appears in the Static Module Index.

    Returns list of warning strings.
    """
    warnings: list[str] = []

    # --- Check 1: Referenced paths exist on disk ---
    checkable_lines: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            checkable_lines.append(line)

    checkable_text = "\n".join(checkable_lines)

    path_pattern = re.compile(r'`(\w[\w/.-]*\.(?:py|ts|tsx|cypher))`')
    seen: set[str] = set()
    for match in path_pattern.finditer(checkable_text):
        ref = match.group(1)
        if ref in seen:
            continue
        seen.add(ref)
        if ref.startswith("*.") or ".." in ref or "/" not in ref:
            continue
        if _resolve_ref_path(ref, pkg_root, web_src):
            continue
        warnings.append(f"path-not-found: {ref}")

    # --- Check 2: Summary Statistics counts ---
    # Find the "Summary Statistics" section and verify counts
    stats_section = re.search(
        r'### \d+\.\d+ Summary Statistics\n\n'
        r'\| Package Area \| Files \|\n\|---\|---\|\n'
        r'((?:\|[^\n]+\n)+)',
        content,
    )
    if stats_section:
        for row_match in re.finditer(r'\| (.+?) \| (\d+) \|', stats_section.group(1)):
            area_name = row_match.group(1).strip()
            claimed = int(row_match.group(2))
            # Find the corresponding section header with count
            header_pat = re.compile(
                rf'###+ \d+(?:\.\d+)? {re.escape(area_name)} \((\d+) files?\)'
            )
            header_match = header_pat.search(content)
            if header_match:
                actual = int(header_match.group(1))
                if actual != claimed:
                    warnings.append(
                        f"stats-mismatch: '{area_name}' header says {actual} but summary says {claimed}"
                    )

    # --- Check 3: No duplicate symbol+file pairs ---
    if symbol_entries is not None:
        seen_syms: dict[tuple[str, str], int] = {}
        for sym_name, sym_file in symbol_entries:
            key = (sym_name, sym_file)
            seen_syms[key] = seen_syms.get(key, 0) + 1
        for (sym, sfile), count in seen_syms.items():
            if count > 1:
                warnings.append(f"duplicate-symbol: '{sym}' in {sfile} appears {count} times")

    # --- Check 4: Entry-point files in static module index ---
    if all_module_paths is not None:
        # Extract .py paths referenced in Entry Point Map section
        ep_section = re.search(r'## 2\. Entry Point Map(.*?)(?=\n---\n|\Z)', content, re.DOTALL)
        if ep_section:
            ep_text = ep_section.group(1)
            # Only check backtick refs in the entry point section (outside code blocks)
            ep_checkable: list[str] = []
            ep_fence = False
            for line in ep_text.split("\n"):
                if line.strip().startswith("```"):
                    ep_fence = not ep_fence
                    continue
                if not ep_fence:
                    ep_checkable.append(line)
            ep_checkable_text = "\n".join(ep_checkable)
            for ep_match in re.finditer(r'`(\w[\w/.-]*\.py)`', ep_checkable_text):
                ep_ref = ep_match.group(1)
                if "/" not in ep_ref:
                    continue
                if ep_ref not in all_module_paths:
                    # Try with common prefixes (entry point map uses abbreviated paths)
                    found = False
                    for prefix in ["commands", "core", "generation", "enrichment", "common"]:
                        if f"{prefix}/{ep_ref}" in all_module_paths:
                            found = True
                            break
                    if not found:
                        warnings.append(f"entry-point-not-in-index: {ep_ref}")

    # --- Check 5: JSON structural checks (task_map, symbols, entry_points) ---
    if index_data is not None:
        sections = index_data.get("sections", {})
        # task_map: every referenced file/dir must exist on disk
        for tm in sections.get("task_map", []):
            for fpath in tm.get("files", []):
                candidate = pkg_root / fpath.rstrip("/")
                if not candidate.exists():
                    warnings.append(f"task-map-missing: '{tm['task']}' references {fpath}")
        # symbols: every symbol file must exist on disk
        sym_files_checked: set[str] = set()
        for sym in sections.get("symbols", []):
            sf = sym.get("file", "")
            if sf and sf not in sym_files_checked:
                sym_files_checked.add(sf)
                if not (pkg_root / sf).exists():
                    warnings.append(f"symbol-file-missing: {sf}")
        # entry_points: every file reference must exist
        for ep in sections.get("entry_points", []):
            ef = ep.get("file")
            if ef and not (pkg_root / ef).exists():
                warnings.append(f"entry-point-file-missing: {ef}")

    return warnings


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def _get_git_info() -> dict[str, Any]:
    """Get current git commit, branch, and dirty state."""
    info: dict[str, Any] = {}
    try:
        info["commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        info["branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        info["dirty"] = len(status) > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return info


def _collect_index_data(
    pkg_name: str,
    pkg_root: Path,
    groups: list[tuple[str, str, str]],
    total: int,
    cgc: Any,
) -> dict[str, Any]:
    """Collect structured index data for JSON output."""
    today = datetime.date.today().isoformat()

    # Modules
    files = collect_py_files(pkg_root)
    modules = []
    for f in files:
        rel = _rel(f, pkg_root)
        gdir = assign_group(rel, groups, pkg_name)
        if gdir is None:
            continue
        group_name = ""
        for _, title, gd in groups:
            if gd == gdir:
                group_name = title
                break
        tags = _classify_module_tags(rel, pkg_name)
        modules.append({
            "path": rel,
            "group": group_name,
            "docstring": extract_module_docstring(f),
            "tags": tags,
        })

    # Entry points — CLI, server, __main__ modules
    entry_points = []
    if pkg_name == "idi":
        pyproject = ROOT / "platform-tools" / "idi" / "pyproject.toml"
    else:
        pyproject = ROOT / "platform-tools" / "vm-builder" / "pyproject.toml"
    scripts = _detect_pyproject_scripts(pyproject)
    for s in scripts:
        if (pkg_name == "idi" and "idi" in s["command"]) or \
           (pkg_name == "vm_builder" and s["command"] == "vm-builder"):
            # Derive file path from module target (e.g. "vm_builder.cli:main" → "cli/__init__.py")
            mod_part = s["target"].split(":")[0]  # "vm_builder.cli"
            rel_mod = mod_part.removeprefix(pkg_name + ".").replace(".", "/")
            file_candidate = pkg_root / rel_mod
            if file_candidate.is_dir():
                cli_file = rel_mod + "/__init__.py"
            elif (pkg_root / (rel_mod + ".py")).exists():
                cli_file = rel_mod + ".py"
            else:
                cli_file = rel_mod + "/__init__.py"
            entry_points.append({
                "name": s["command"],
                "type": "cli",
                "module": s["target"],
                "file": cli_file,
            })

    # __main__.py entry points
    for main_file in sorted(pkg_root.rglob("__main__.py")):
        rel = _rel(main_file, pkg_root)
        parts = rel.replace("/__main__.py", "").split("/")
        module_path = f"{pkg_name}.{'.'.join(parts)}"
        entry_points.append({
            "name": f"python -m {module_path}",
            "type": "python_module",
            "module": module_path,
            "file": rel,
        })

    # Server entry points
    if pkg_name == "idi":
        mcp_server = pkg_root / "mcp" / "server.py"
        if mcp_server.exists():
            entry_points.append({
                "name": "python -m idi.mcp.server",
                "type": "mcp_server",
                "module": "idi.mcp.server",
                "file": "mcp/server.py",
                "transport": "stdio",
            })
    elif pkg_name == "vm_builder":
        app_file = pkg_root / "api" / "app.py"
        if app_file.exists():
            entry_points.append({
                "name": "vm_builder.api.app:app",
                "type": "asgi",
                "module": "vm_builder.api.app",
                "file": "api/app.py",
                "framework": "FastAPI",
            })

    # Symbols — with module tags inherited for edit-safety signals
    symbol_dirs = _IDI_SYMBOL_DIRS if pkg_name == "idi" else _VM_SYMBOL_DIRS
    symbols = []
    for py_file in _collect_symbol_files(pkg_name, pkg_root, symbol_dirs):
        rel = _rel(py_file, pkg_root)
        mod_tags = _classify_module_tags(rel, pkg_name)
        # Build Python import path: idi.mcp.tools.query or vm_builder.core.vm_service
        mod_import = pkg_name + "." + rel.replace("/", ".").removesuffix(".py")
        for sym_name, kind, line_start, line_end in _extract_public_symbols(py_file):
            # Top-level name (strip Class.method to just Class for import_path)
            top_sym = sym_name.split(".")[0]
            symbols.append({
                "name": sym_name, "file": rel, "kind": kind,
                "tags": mod_tags,
                "import_path": f"{mod_import}:{top_sym}",
                "line_start": line_start, "line_end": line_end,
            })

    # Deterministic order: file, kind, name
    symbols.sort(key=lambda s: (s["file"], s["kind"], s["name"].lower()))

    # Cheat sheet + task_map (resolved paths)
    cheat_templates = _IDI_CHEAT_SHEET if pkg_name == "idi" else _VM_CHEAT_SHEET
    cheat_sheet = []
    task_map = []
    for entry in cheat_templates:
        checks = entry["check"]
        if checks and not any((pkg_root / c).exists() for c in checks):
            continue
        cheat_sheet.append({
            "task": entry["task"],
            "description": entry["desc"],
        })
        # Resolve check paths to actual files/dirs for task_map
        resolved_paths: list[str] = []
        for c in checks:
            candidate = pkg_root / c
            if candidate.is_file():
                resolved_paths.append(c)
            elif candidate.is_dir():
                resolved_paths.append(c + "/")
        task_map.append({
            "task": entry["task"],
            "files": resolved_paths,
            "description": entry["desc"],
        })

    result: dict[str, Any] = {
        "package": pkg_name,
        "generated_at": today,
        "total_modules": total,
        "cgc_mode": cgc is not None,
        "git": _get_git_info(),
        "surface_dirs": symbol_dirs,
        "sections": {
            "modules": modules,
            "entry_points": entry_points,
            "symbols": symbols,
            "cheat_sheet": cheat_sheet,
            "task_map": task_map,
        },
    }
    return result


def _write_json_index(data: dict[str, Any], output_path: Path) -> None:
    """Write structured index data as JSON."""
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# Volatile fields stripped during --check JSON comparison so that
# generated_at / git metadata don't cause false staleness.
_JSON_VOLATILE_KEYS = {"generated_at", "git"}


def _strip_volatile(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *data* without volatile keys."""
    return {k: v for k, v in data.items() if k not in _JSON_VOLATILE_KEYS}


# Regex to normalize the date in the markdown header for --check comparison.
_DATE_LINE_RE = re.compile(r'(\*Generated by .+? on )\d{4}-\d{2}-\d{2}( .+\*)')


def _strip_md_date(content: str) -> str:
    """Replace the generated-on date with a fixed placeholder so --check is date-agnostic."""
    return _DATE_LINE_RE.sub(r'\g<1>DATE\2', content, count=1)


# ---------------------------------------------------------------------------
# Main assembly
# ---------------------------------------------------------------------------

def generate_index(
    pkg_name: str,
    pkg_root: Path,
    groups: list[tuple[str, str, str]],
    output_path: Path,
    display_name: str,
    check: bool = False,
    cgc: Any = None,
) -> bool:
    """Generate or check an index file. Returns True if up-to-date."""
    section0 = generate_cheat_sheet(pkg_name, pkg_root)
    section1, total = generate_section1(pkg_name, pkg_root, groups, display_name, cgc=cgc)

    # Append symbol index to section 1
    symbol_index = generate_symbol_index(pkg_name, pkg_root)
    if symbol_index:
        section1 = section1 + "\n\n" + symbol_index

    if pkg_name == "idi":
        section2 = generate_entry_point_map_idi(pkg_root, cgc)
        section3 = generate_mcp_tool_map(pkg_root)
        section4 = generate_external_deps_idi(pkg_root, cgc)
        section5 = generate_arch_patterns_idi(pkg_root)
    else:
        section2 = generate_entry_point_map_vm(pkg_root, cgc)
        section3 = generate_api_route_map(pkg_root)
        section4 = generate_external_deps_vm(pkg_root, cgc)
        # VM Builder gets arch patterns + web index combined as section 5
        web_src = pkg_root.parent / "vm-builder-web" / "src"
        section5_parts = [generate_arch_patterns_vm(pkg_root)]
        if web_src.exists():
            section5_parts.append(generate_web_index(web_src))
        section5 = "\n\n---\n\n".join(section5_parts)

    sections = [section0, section1, section2, section3, section4, section5]
    full_content = "\n\n---\n\n".join(sections) + "\n"

    # Collect structured data for JSON output (needed for consistency checks too)
    index_data = _collect_index_data(pkg_name, pkg_root, groups, total, cgc)

    # Run consistency checks with structural validation
    web_src = pkg_root.parent / "vm-builder-web" / "src" if pkg_name == "vm_builder" else None
    all_module_paths = {m["path"] for m in index_data["sections"]["modules"]}
    symbol_entries = [(s["name"], s["file"]) for s in index_data["sections"]["symbols"]]
    consistency_warnings = _validate_consistency(
        full_content, pkg_root, web_src,
        all_module_paths=all_module_paths,
        symbol_entries=symbol_entries,
        index_data=index_data,
    )
    if consistency_warnings:
        for w in consistency_warnings:
            print(f"WARNING [{pkg_name}]: {w}", file=sys.stderr)
    json_path = output_path.with_suffix(".json")

    if check:
        if not output_path.exists():
            print(f"STALE: {output_path} does not exist")
            return False
        existing = output_path.read_text(encoding="utf-8")
        if _strip_md_date(existing) != _strip_md_date(full_content):
            print(f"STALE: {output_path} needs regeneration ({total} modules)")
            return False
        # Check JSON file too — strip volatile fields before comparison
        if json_path.exists():
            existing_json = json.loads(json_path.read_text(encoding="utf-8"))
            if _strip_volatile(existing_json) != _strip_volatile(index_data):
                print(f"STALE: {json_path} needs regeneration")
                return False
        else:
            print(f"STALE: {json_path} does not exist")
            return False
        if consistency_warnings:
            print(f"INCONSISTENT: {output_path} has {len(consistency_warnings)} path reference(s) to non-existent files")
            return False
        print(f"OK: {output_path} is up to date ({total} modules)")
        return True

    output_path.write_text(full_content, encoding="utf-8")
    _write_json_index(index_data, json_path)
    print(f"Generated {output_path} ({total} modules)")
    print(f"Generated {json_path} ({len(index_data['sections']['symbols'])} symbols)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate module index docs.")
    parser.add_argument("--check", action="store_true", help="Check if indexes are up to date (exit 1 if stale)")
    parser.add_argument("--no-cgc", action="store_true", help="Skip CGC FalkorDB queries (graceful fallback)")
    args = parser.parse_args()

    cgc = None
    if not args.no_cgc:
        cgc = _cgc_connect()
        if cgc:
            print("CGC FalkorDB connected")
        else:
            print("CGC not available — using AST-only mode")

    docs_dir = ROOT / "docs"

    ok1 = generate_index(
        pkg_name="idi",
        pkg_root=ROOT / "platform-tools" / "idi" / "idi",
        groups=IDI_GROUPS,
        output_path=docs_dir / "IDI-INDEX.md",
        display_name="IDI",
        check=args.check,
        cgc=cgc,
    )

    ok2 = generate_index(
        pkg_name="vm_builder",
        pkg_root=ROOT / "platform-tools" / "vm-builder" / "vm_builder",
        groups=VM_BUILDER_GROUPS,
        output_path=docs_dir / "VM-BUILDER-INDEX.md",
        display_name="VM Builder",
        check=args.check,
        cgc=cgc,
    )

    if cgc:
        try:
            cgc.close()
        except Exception:
            pass

    if args.check and not (ok1 and ok2):
        sys.exit(1)


if __name__ == "__main__":
    main()
