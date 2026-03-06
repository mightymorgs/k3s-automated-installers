"""Request construction utilities for VM create command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import yaml

from vm_builder.core.models import VmCreateRequest

_REQUIRED_FIELDS = ("vm_name", "size", "platform")


def load_config(config_path: str) -> dict[str, Any]:
    """Load and minimally validate VM YAML config."""
    try:
        raw = yaml.safe_load(Path(config_path).read_text())
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR: Failed to load config: {exc}", err=True)
        raise click.Abort() from exc

    if not isinstance(raw, dict):
        click.echo("ERROR: Config file must define a YAML object", err=True)
        raise click.Abort()

    for field in _REQUIRED_FIELDS:
        if field not in raw:
            click.echo(f"ERROR: Missing required field in config: {field}", err=True)
            raise click.Abort()

    return raw


def build_request(config: dict[str, Any]) -> VmCreateRequest:
    """Build ``VmCreateRequest`` from loaded config."""
    apps_raw = config.get("apps")
    apps = apps_raw.get("selected_apps") if isinstance(apps_raw, dict) else apps_raw

    return VmCreateRequest(
        vm_name=config["vm_name"],
        size=config["size"],
        platform=config["platform"],
        vcpu=config.get("vcpu"),
        memory_mb=config.get("memory_mb"),
        disk_size_gb=config.get("disk_size_gb"),
        data_disk_size_gb=config.get("data_disk_size_gb"),
        enable_gpu_passthrough=config.get("enable_gpu_passthrough"),
        gpu_pci_address=config.get("gpu_pci_address"),
        network_mode=config.get("network_mode"),
        bridge=config.get("bridge"),
        static_ip=config.get("static_ip"),
        gateway=config.get("gateway"),
        dns=config.get("dns"),
        libvirt_uri=config.get("libvirt_uri"),
        base_image_path=config.get("base_image_path"),
        ssh_authorized_keys=config.get("ssh_authorized_keys"),
        iac_version=config.get("iac_version"),
        apps=apps,
        gcp=config.get("gcp"),
    )

