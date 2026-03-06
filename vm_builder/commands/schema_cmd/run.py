"""Schema command handlers."""

from __future__ import annotations

import json
import click
from rich.console import Console
from rich.table import Table

from vm_builder import schema
from vm_builder.schema import GCP_SIZE_PRESETS, RESOURCE_DEFAULTS, SIZE_PRESETS

_console = Console()
_BANNER = "=" * 70

_PLATFORMS = {
    "libvirt": {
        "description": "Local KVM/QEMU via libvirt",
        "sizes": list(SIZE_PRESETS.keys()),
    },
    "gcp": {
        "description": "Google Cloud Platform Compute Engine",
        "sizes": list(GCP_SIZE_PRESETS.keys()),
    },
}


def show_sizes(platform: str | None, as_json: bool) -> None:
    """Display VM size presets, optionally filtered by platform."""
    click.echo(_BANNER)
    click.echo("VM Size Presets")
    click.echo(_BANNER)
    click.echo()

    if platform == "gcp":
        presets = GCP_SIZE_PRESETS
    elif platform == "libvirt" or platform is None:
        presets = SIZE_PRESETS
    else:
        click.echo(f"ERROR: Unknown platform: {platform}", err=True)
        raise click.Abort()

    if as_json:
        click.echo(json.dumps(presets, indent=2))
        return

    table = Table(title="Size Presets")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("vCPU", justify="right", style="green")
    table.add_column("Memory", justify="right", style="blue")
    table.add_column("Disk", justify="right", style="yellow")

    for name, spec in presets.items():
        vcpu = str(spec.get("vcpu", spec.get("machine_type", "")))
        mem = spec.get("memory_mb")
        memory = f"{mem} MB" if mem else f"{spec.get('memory_gb', '?')} GB"
        disk = f"{spec.get('disk_size_gb', spec.get('boot_disk_size_gb', '?'))} GB"
        table.add_row(name, vcpu, memory, disk)

    _console.print(table)


def show_platforms() -> None:
    """List supported platforms."""
    click.echo(_BANNER)
    click.echo("Supported Platforms")
    click.echo(_BANNER)
    click.echo()

    table = Table(title="Platforms")
    table.add_column("Platform", style="cyan", no_wrap=True)
    table.add_column("Description", style="green")
    table.add_column("Sizes", style="blue")

    for name, info in _PLATFORMS.items():
        table.add_row(name, info["description"], ", ".join(info["sizes"]))

    _console.print(table)


def validate_name(name: str) -> None:
    """Validate a VM name format and display parsed components."""
    click.echo(_BANNER)
    click.echo(f"Validate VM Name: {name}")
    click.echo(_BANNER)
    click.echo()

    is_valid, components, errors = schema.parse_vm_name(name)
    if is_valid:
        click.echo("OK: Valid VM name")
        click.echo()
        for key, value in components.items():
            click.echo(f"  {key}: {value}")
    else:
        click.echo("FAIL: Invalid VM name", err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        raise click.Abort()


def show_resource_defaults() -> None:
    """Display resource requirements by category."""
    click.echo(_BANNER)
    click.echo("Resource Defaults by Category")
    click.echo(_BANNER)
    click.echo()

    table = Table(title="Resource Defaults")
    table.add_column("Category", style="cyan", no_wrap=True)
    table.add_column("Min CPU (m)", justify="right", style="green")
    table.add_column("Min Mem (MB)", justify="right", style="blue")
    table.add_column("Rec CPU (m)", justify="right", style="green")
    table.add_column("Rec Mem (MB)", justify="right", style="blue")

    for cat, d in RESOURCE_DEFAULTS.items():
        if cat == "_default":
            continue
        table.add_row(cat, str(d["min_cpu_millicores"]), str(d["min_memory_mb"]),
                       str(d["recommended_cpu_millicores"]), str(d["recommended_memory_mb"]))
    _console.print(table)
