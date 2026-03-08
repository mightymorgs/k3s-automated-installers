"""CLI entry point for VM Builder repo skill generation."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from vm_builder.skills.orchestrator import generate_skills


def cli(argv: Sequence[str] | None = None) -> int:
    """Run the VM Builder skill generator CLI."""
    parser = argparse.ArgumentParser(description="Generate vm-builder atomic skills")
    parser.add_argument("--generate", action="store_true", help="Generate all skills")
    parser.add_argument("--check", action="store_true", help="Check for stale skills")
    parser.add_argument(
        "--source",
        default="idi-platform-tools/vm-builder/vm_builder",
        help="Path to vm_builder package",
    )
    parser.add_argument(
        "--output",
        default="catalog/skills/repo/vm-builder",
        help="Output directory for skill files",
    )
    args = parser.parse_args(argv)

    source_root = Path(args.source)
    output_dir = Path(args.output)

    if args.generate:
        print(f"Generating skills from {source_root} -> {output_dir}")
        files = generate_skills(source_root=source_root, output_dir=output_dir)
        print(f"Generated {len(files)} skill files")
        for file_path in sorted(files):
            print(f"  {file_path}")
        return 0

    if args.check:
        print("Check mode not yet implemented")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())

