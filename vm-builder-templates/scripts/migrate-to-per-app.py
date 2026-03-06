#!/usr/bin/env python3
"""Migrate vm-builder-templates to per-app directory structure.

Reorganizes scattered app files from ansible/playbooks/atomic/apps/,
ansible/playbooks/atomic/storage/, k8s/platform/, k8s/apps/, k8s/storage/,
ansible/templates/k8s/platform/, and ansible/values/ into a unified
apps/{app}/ directory structure.

Usage:
    python scripts/migrate-to-per-app.py --dry-run                    # Show what would move (default)
    python scripts/migrate-to-per-app.py --dry-run --output-map docs/migration-map.md  # Also write mapping doc
    python scripts/migrate-to-per-app.py --execute                    # Actually move files
    python scripts/migrate-to-per-app.py --rollback                   # Reverse from mapping doc
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Source categories that are eligible for migration.
# Everything NOT listed here is explicitly skipped.
# ---------------------------------------------------------------------------

# Directories under ansible/playbooks/atomic/ that are NOT moved.
SKIP_ATOMIC_CATEGORIES = {"platform", "networking", "tools", "hypervisor"}

# Top-level dirs under ansible/ that are NOT moved (besides playbooks/atomic/apps|storage).
# ansible/playbooks/orchestration/, ansible/templates/cloud-init|inventory|k3s/ are skipped.

# infra/ at repo root is NOT moved.


def _repo_root_default() -> Path:
    """Return the vm-builder-templates root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. scan_current_layout
# ---------------------------------------------------------------------------

def scan_current_layout(repo_root: Path) -> dict[str, list[Path]]:
    """Scan all source locations and return {app_name: [file_paths]}.

    Paths are absolute. Only files that should be migrated are included.
    """
    apps: dict[str, list[Path]] = defaultdict(list)

    # --- ansible/playbooks/atomic/apps/{app}/ ---
    ansible_apps_dir = repo_root / "ansible" / "playbooks" / "atomic" / "apps"
    if ansible_apps_dir.is_dir():
        for app_dir in sorted(ansible_apps_dir.iterdir()):
            if app_dir.is_dir():
                for f in app_dir.rglob("*"):
                    if f.is_file():
                        apps[app_dir.name].append(f)

    # --- ansible/playbooks/atomic/storage/{app}/ ---
    ansible_storage_dir = repo_root / "ansible" / "playbooks" / "atomic" / "storage"
    if ansible_storage_dir.is_dir():
        for app_dir in sorted(ansible_storage_dir.iterdir()):
            if app_dir.is_dir():
                for f in app_dir.rglob("*"):
                    if f.is_file():
                        apps[app_dir.name].append(f)

    # --- k8s/platform/{app}/ ---
    k8s_platform_dir = repo_root / "k8s" / "platform"
    if k8s_platform_dir.is_dir():
        for item in sorted(k8s_platform_dir.iterdir()):
            if item.is_dir():
                for f in item.rglob("*"):
                    if f.is_file():
                        apps[item.name].append(f)
            # Skip root-level files in k8s/platform/ (e.g., README.md)

    # --- k8s/apps/{app}/ ---
    k8s_apps_dir = repo_root / "k8s" / "apps"
    if k8s_apps_dir.is_dir():
        for app_dir in sorted(k8s_apps_dir.iterdir()):
            if app_dir.is_dir():
                for f in app_dir.rglob("*"):
                    if f.is_file():
                        apps[app_dir.name].append(f)

    # --- k8s/storage/{app}/ ---
    k8s_storage_dir = repo_root / "k8s" / "storage"
    if k8s_storage_dir.is_dir():
        for app_dir in sorted(k8s_storage_dir.iterdir()):
            if app_dir.is_dir():
                for f in app_dir.rglob("*"):
                    if f.is_file():
                        apps[app_dir.name].append(f)

    # --- ansible/templates/k8s/platform/{app}/ ---
    templates_dir = repo_root / "ansible" / "templates" / "k8s" / "platform"
    if templates_dir.is_dir():
        for app_dir in sorted(templates_dir.iterdir()):
            if app_dir.is_dir():
                for f in app_dir.rglob("*"):
                    if f.is_file():
                        apps[app_dir.name].append(f)

    # --- ansible/values/{app}/ ---
    values_dir = repo_root / "ansible" / "values"
    if values_dir.is_dir():
        for app_dir in sorted(values_dir.iterdir()):
            if app_dir.is_dir():
                for f in app_dir.rglob("*"):
                    if f.is_file():
                        apps[app_dir.name].append(f)

    return dict(apps)


# ---------------------------------------------------------------------------
# 2. build_migration_map
# ---------------------------------------------------------------------------

def _compute_target(src_rel: Path, repo_root: Path) -> Path | None:
    """Map a single source relative path to its target relative path.

    Returns None if the file should be skipped.
    """
    parts = src_rel.parts

    # --- ansible/playbooks/atomic/apps/{app}/... -> apps/{app}/... ---
    if (
        len(parts) >= 6
        and parts[0] == "ansible"
        and parts[1] == "playbooks"
        and parts[2] == "atomic"
        and parts[3] == "apps"
    ):
        app_name = parts[4]
        # Everything under apps/{app}/ preserves internal structure.
        remainder = Path(*parts[5:])
        return Path("apps") / app_name / remainder

    # --- ansible/playbooks/atomic/storage/{app}/... -> apps/{app}/... ---
    if (
        len(parts) >= 6
        and parts[0] == "ansible"
        and parts[1] == "playbooks"
        and parts[2] == "atomic"
        and parts[3] == "storage"
    ):
        app_name = parts[4]
        remainder = Path(*parts[5:])
        return Path("apps") / app_name / remainder

    # --- k8s/platform/{app}/base/... -> apps/{app}/k8s-base/... ---
    # --- k8s/platform/{app}/<root files> -> apps/{app}/k8s-base/... ---
    # --- k8s/platform/{app}/<other dirs>/... -> apps/{app}/k8s-base/<other dirs>/... ---
    if (
        len(parts) >= 4
        and parts[0] == "k8s"
        and parts[1] == "platform"
    ):
        app_name = parts[2]
        # Everything under k8s/platform/{app}/ goes to apps/{app}/k8s-base/
        # with base/ stripped (base/ contents go directly into k8s-base/).
        sub_parts = parts[3:]
        if sub_parts[0] == "base":
            # k8s/platform/{app}/base/file.yaml -> apps/{app}/k8s-base/file.yaml
            remainder = Path(*sub_parts[1:]) if len(sub_parts) > 1 else None
            if remainder is None:
                return None  # Should not happen (we only process files)
            return Path("apps") / app_name / "k8s-base" / remainder
        else:
            # Root-level files or non-base subdirs (overlays, examples, etc.)
            # go into k8s-base/ preserving structure relative to the app dir.
            remainder = Path(*sub_parts)
            return Path("apps") / app_name / "k8s-base" / remainder

    # --- k8s/apps/{app}/... -> apps/{app}/k8s-standalone/... ---
    if (
        len(parts) >= 4
        and parts[0] == "k8s"
        and parts[1] == "apps"
    ):
        app_name = parts[2]
        remainder = Path(*parts[3:])
        return Path("apps") / app_name / "k8s-standalone" / remainder

    # --- k8s/storage/{app}/... -> apps/{app}/k8s-storage/... ---
    if (
        len(parts) >= 4
        and parts[0] == "k8s"
        and parts[1] == "storage"
    ):
        app_name = parts[2]
        remainder = Path(*parts[3:])
        return Path("apps") / app_name / "k8s-storage" / remainder

    # --- ansible/templates/k8s/platform/{app}/... -> apps/{app}/templates/... ---
    if (
        len(parts) >= 6
        and parts[0] == "ansible"
        and parts[1] == "templates"
        and parts[2] == "k8s"
        and parts[3] == "platform"
    ):
        app_name = parts[4]
        remainder = Path(*parts[5:])
        return Path("apps") / app_name / "templates" / remainder

    # --- ansible/values/{app}/... -> apps/{app}/values/... ---
    if (
        len(parts) >= 4
        and parts[0] == "ansible"
        and parts[1] == "values"
    ):
        app_name = parts[2]
        remainder = Path(*parts[3:])
        return Path("apps") / app_name / "values" / remainder

    return None


def build_migration_map(repo_root: Path) -> list[tuple[Path, Path]]:
    """Return [(old_relative_path, new_relative_path)] for every file to move.

    All paths are relative to repo_root.
    """
    layout = scan_current_layout(repo_root)
    migrations: list[tuple[Path, Path]] = []

    for app_name in sorted(layout.keys()):
        for abs_path in sorted(layout[app_name]):
            src_rel = abs_path.relative_to(repo_root)
            target_rel = _compute_target(src_rel, repo_root)
            if target_rel is not None:
                migrations.append((src_rel, target_rel))

    return migrations


# ---------------------------------------------------------------------------
# 3. generate_mapping_doc
# ---------------------------------------------------------------------------

def generate_mapping_doc(
    migrations: list[tuple[Path, Path]],
    repo_root: Path,
) -> str:
    """Generate a Markdown mapping document from the migration list."""
    lines: list[str] = []
    lines.append("# Migration Map: vm-builder-templates -> per-app structure")
    lines.append("")
    lines.append(f"Generated by `scripts/migrate-to-per-app.py`")
    lines.append("")

    # Group by app
    by_app: dict[str, list[tuple[Path, Path]]] = defaultdict(list)
    for src, dst in migrations:
        # App name is always the second component of the target: apps/{app}/...
        app_name = dst.parts[1]
        by_app[app_name].append((src, dst))

    lines.append(f"## Summary")
    lines.append("")
    lines.append(f"- **Total files:** {len(migrations)}")
    lines.append(f"- **Total apps:** {len(by_app)}")
    lines.append("")

    lines.append("| App | Files |")
    lines.append("|-----|-------|")
    for app_name in sorted(by_app.keys()):
        lines.append(f"| {app_name} | {len(by_app[app_name])} |")
    lines.append("")

    # Per-app details
    for app_name in sorted(by_app.keys()):
        lines.append(f"## {app_name}")
        lines.append("")
        lines.append("| Source | Target |")
        lines.append("|--------|--------|")
        for src, dst in sorted(by_app[app_name]):
            lines.append(f"| `{src}` | `{dst}` |")
        lines.append("")

    # Skipped files section
    lines.append("## Skipped Directories")
    lines.append("")
    lines.append("The following directories are **not moved** by this migration:")
    lines.append("")
    skip_list = [
        ("`ansible/playbooks/atomic/platform/`", "Platform bootstrap playbooks (k3s, authentik, vault, traefik, ingress)"),
        ("`ansible/playbooks/atomic/networking/`", "Networking playbooks"),
        ("`ansible/playbooks/atomic/tools/`", "Tools playbooks"),
        ("`ansible/playbooks/atomic/hypervisor/`", "Hypervisor playbooks"),
        ("`ansible/playbooks/orchestration/`", "Orchestration playbooks"),
        ("`ansible/templates/cloud-init/`", "Cloud-init templates"),
        ("`ansible/templates/inventory/`", "Inventory templates"),
        ("`ansible/templates/k3s/`", "K3s templates"),
        ("`infra/`", "Infrastructure (Terraform/Terragrunt)"),
        ("`k8s/platform/README.md`", "Platform-level README"),
    ]
    lines.append("| Path | Reason |")
    lines.append("|------|--------|")
    for path, reason in skip_list:
        lines.append(f"| {path} | {reason} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. execute_migration
# ---------------------------------------------------------------------------

def execute_migration(
    migrations: list[tuple[Path, Path]],
    repo_root: Path,
) -> None:
    """Move files according to the migration map.

    Idempotent: skips if target exists and source does not.
    Errors if both source and target exist (conflict).
    Removes empty parent directories after moving.
    """
    moved = 0
    skipped = 0
    errors = 0

    for src_rel, dst_rel in migrations:
        src_abs = repo_root / src_rel
        dst_abs = repo_root / dst_rel

        # Idempotent check
        if dst_abs.exists() and not src_abs.exists():
            skipped += 1
            continue

        if dst_abs.exists() and src_abs.exists():
            print(f"  CONFLICT: both exist: {src_rel} -> {dst_rel}", file=sys.stderr)
            errors += 1
            continue

        if not src_abs.exists():
            print(f"  MISSING: source not found: {src_rel}", file=sys.stderr)
            errors += 1
            continue

        # Create target directory
        dst_abs.parent.mkdir(parents=True, exist_ok=True)

        # Move the file
        shutil.move(str(src_abs), str(dst_abs))
        moved += 1

        if moved % 20 == 0:
            print(f"  ... moved {moved} files")

    # Clean up empty directories left behind
    empty_removed = _remove_empty_dirs(repo_root)

    print(f"\nMigration complete:")
    print(f"  Moved:   {moved}")
    print(f"  Skipped: {skipped} (already migrated)")
    print(f"  Errors:  {errors}")
    print(f"  Empty dirs removed: {empty_removed}")

    if errors > 0:
        print(f"\nWARNING: {errors} errors occurred. Check output above.", file=sys.stderr)
        sys.exit(1)


def _remove_empty_dirs(repo_root: Path) -> int:
    """Walk the repo and remove empty directories that were left behind.

    Only removes directories under the source paths (ansible/, k8s/).
    Does NOT remove the top-level ansible/ or k8s/ directories themselves.
    Returns count of directories removed.
    """
    removed = 0
    source_roots = [
        repo_root / "ansible" / "playbooks" / "atomic" / "apps",
        repo_root / "ansible" / "playbooks" / "atomic" / "storage",
        repo_root / "k8s" / "platform",
        repo_root / "k8s" / "apps",
        repo_root / "k8s" / "storage",
        repo_root / "ansible" / "templates" / "k8s" / "platform",
        repo_root / "ansible" / "values",
    ]

    for root_dir in source_roots:
        if not root_dir.is_dir():
            continue
        # Walk bottom-up to remove leaf-empty dirs first
        for dirpath in sorted(root_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                dirpath.rmdir()
                removed += 1

        # Check if the root_dir itself is now empty
        if root_dir.is_dir() and not any(root_dir.iterdir()):
            root_dir.rmdir()
            removed += 1

    return removed


# ---------------------------------------------------------------------------
# 5. rollback_migration
# ---------------------------------------------------------------------------

def rollback_migration(mapping_doc: Path, repo_root: Path) -> None:
    """Parse the mapping doc and reverse all moves.

    Reads the markdown table rows and swaps source/target.
    """
    if not mapping_doc.exists():
        print(f"ERROR: mapping doc not found: {mapping_doc}", file=sys.stderr)
        sys.exit(1)

    text = mapping_doc.read_text()

    # Extract all (source, target) pairs from markdown table rows.
    # Pattern matches: | `some/path` | `some/other/path` |
    pattern = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|$", re.MULTILINE)
    pairs = pattern.findall(text)

    if not pairs:
        print("ERROR: no migration pairs found in mapping doc.", file=sys.stderr)
        sys.exit(1)

    # Filter to only file migration rows (skip summary table rows and skipped dirs).
    # File migration rows have paths that look like file paths (contain / and a file extension).
    migration_pairs: list[tuple[Path, Path]] = []
    for src_str, dst_str in pairs:
        src = Path(src_str)
        dst = Path(dst_str)
        # Valid migration pairs have targets starting with "apps/"
        if dst.parts[0] == "apps" and len(dst.parts) >= 3:
            migration_pairs.append((src, dst))

    print(f"Found {len(migration_pairs)} file moves to reverse.")

    # Reverse: move from target back to source
    reversed_migrations = [(dst, src) for src, dst in migration_pairs]
    moved = 0
    skipped = 0
    errors = 0

    for current_rel, original_rel in reversed_migrations:
        current_abs = repo_root / current_rel
        original_abs = repo_root / original_rel

        if original_abs.exists() and not current_abs.exists():
            skipped += 1
            continue

        if original_abs.exists() and current_abs.exists():
            print(f"  CONFLICT: both exist: {current_rel} -> {original_rel}", file=sys.stderr)
            errors += 1
            continue

        if not current_abs.exists():
            print(f"  MISSING: {current_rel} (already rolled back?)", file=sys.stderr)
            skipped += 1
            continue

        original_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(current_abs), str(original_abs))
        moved += 1

    # Clean up empty apps/ directories
    apps_dir = repo_root / "apps"
    empty_removed = 0
    if apps_dir.is_dir():
        for dirpath in sorted(apps_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                dirpath.rmdir()
                empty_removed += 1
        if apps_dir.is_dir() and not any(apps_dir.iterdir()):
            apps_dir.rmdir()
            empty_removed += 1

    print(f"\nRollback complete:")
    print(f"  Restored: {moved}")
    print(f"  Skipped:  {skipped}")
    print(f"  Errors:   {errors}")
    print(f"  Empty dirs removed: {empty_removed}")

    if errors > 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate vm-builder-templates to per-app directory structure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would move without making changes (default).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Actually move files.",
    )
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="Reverse migration using the mapping doc.",
    )

    parser.add_argument(
        "--output-map",
        type=str,
        default=None,
        help="Path to write the mapping doc (relative to repo root). Default: docs/migration-map.md",
    )
    parser.add_argument(
        "--repo-root",
        type=str,
        default=None,
        help="Override repo root (default: parent of scripts/ dir).",
    )

    args = parser.parse_args()

    # Resolve repo root
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = _repo_root_default()

    if not repo_root.is_dir():
        print(f"ERROR: repo root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    # Resolve mapping doc path
    if args.output_map:
        mapping_doc_path = repo_root / args.output_map
    else:
        mapping_doc_path = repo_root / "docs" / "migration-map.md"

    # --- Rollback mode ---
    if args.rollback:
        print(f"Rolling back migration using: {mapping_doc_path}")
        rollback_migration(mapping_doc_path, repo_root)
        return

    # --- Build migration map ---
    print(f"Scanning: {repo_root}")
    migrations = build_migration_map(repo_root)

    if not migrations:
        print("No files found to migrate.")
        return

    # Group by app for summary
    by_app: dict[str, int] = defaultdict(int)
    for _, dst in migrations:
        app_name = dst.parts[1]
        by_app[app_name] += 1

    print(f"\n{len(migrations)} files to move across {len(by_app)} apps:\n")
    for app_name in sorted(by_app.keys()):
        print(f"  {app_name:30s} {by_app[app_name]:3d} files")
    print()

    # --- Execute mode ---
    if args.execute:
        # Always write mapping doc before executing (for rollback support)
        mapping_doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc = generate_mapping_doc(migrations, repo_root)
        mapping_doc_path.write_text(doc)
        print(f"Mapping doc written to: {mapping_doc_path}")
        print(f"\nExecuting migration...")
        execute_migration(migrations, repo_root)
        return

    # --- Dry-run mode ---
    # Print detailed mapping
    current_app = None
    for src, dst in migrations:
        app_name = dst.parts[1]
        if app_name != current_app:
            current_app = app_name
            print(f"--- {app_name} ---")
        print(f"  {src}")
        print(f"    -> {dst}")

    # Optionally write mapping doc
    if args.output_map is not None:
        mapping_doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc = generate_mapping_doc(migrations, repo_root)
        mapping_doc_path.write_text(doc)
        print(f"\nMapping doc written to: {mapping_doc_path}")

    print(f"\nDry run complete. Use --execute to perform the migration.")


if __name__ == "__main__":
    main()
