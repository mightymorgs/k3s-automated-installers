#!/usr/bin/env python3
"""Generate .idi-meta.yaml sidecar files for VM builder templates.

Usage:
    python scripts/generate_template_sidecars.py --generate [--templates-dir DIR]
    python scripts/generate_template_sidecars.py --validate [--templates-dir DIR]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "platform-tools" / "vm-builder"))

from vm_builder.template_sidecars.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli())
