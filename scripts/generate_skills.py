#!/usr/bin/env python3
"""Generate atomic skill JSON from downloaded specs.

Usage:
    python scripts/generate_skills.py [--service NAME] [--dry-run]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idi.generation.generate_all import cli

if __name__ == "__main__":
    raise SystemExit(cli())
