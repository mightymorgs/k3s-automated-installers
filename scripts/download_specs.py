#!/usr/bin/env python3
"""Download OpenAPI specs and CRD schemas for all services in catalog/manifest.yaml.

Usage:
    python scripts/download_specs.py [--service NAME] [--force]
"""
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "platform-tools" / "idi"))

from idi.generation.download_specs import cli

if __name__ == "__main__":
    raise SystemExit(cli())
