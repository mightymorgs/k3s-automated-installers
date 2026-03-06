"""CLI entry point for template sidecar generation."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from vm_builder.template_sidecars.orchestrator import generate_all_sidecars


def cli(argv: Sequence[str] | None = None) -> int:
    """Run sidecar generation or schema validation."""
    parser = argparse.ArgumentParser(description="Generate .idi-meta.yaml sidecars")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--templates-dir",
        default="vm-builder-templates",
        help="Path to templates directory",
    )
    args = parser.parse_args(argv)

    templates = Path(args.templates_dir)

    if args.generate:
        print(f"Generating sidecars for {templates}")
        total = generate_all_sidecars(templates)
        print(f"Done - {total} sidecars generated")
        return 0

    if args.validate:
        result = subprocess.run(
            ["python", "scripts/validate_idi_meta.py", str(templates)],
            check=False,
        )
        return result.returncode

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())

