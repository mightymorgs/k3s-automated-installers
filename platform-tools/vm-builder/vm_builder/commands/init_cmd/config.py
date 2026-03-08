"""Configuration loading for init command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml


def load_config(config_path: str | None) -> dict[str, Any]:
    """Load optional YAML config for secret defaults."""
    if not config_path:
        return {}

    try:
        loaded = yaml.safe_load(Path(config_path).read_text()) or {}
    except Exception as exc:  # noqa: BLE001
        click.echo(f"WARNING: Failed to load config: {exc}", err=True)
        return {}

    if not isinstance(loaded, dict):
        click.echo("WARNING: Config is not a YAML object; ignoring", err=True)
        return {}

    click.echo(f"OK: Loaded config from: {config_path}")
    return loaded

