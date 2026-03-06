"""Prompt resolution for hypervisor bootstrap command."""

from __future__ import annotations

import click

from vm_builder.core.models import HypervisorConfig


def resolve_hypervisor_config(
    name: str,
    local_ip: str | None = None,
    github_repo: str | None = None,
    network_mode: str | None = None,
    platform: str | None = None,
    location: str | None = None,
) -> HypervisorConfig:
    """Resolve missing hypervisor values via interactive prompts."""
    resolved_platform = platform or click.prompt("Platform (libvirt/vsphere/...)", default="libvirt")
    resolved_location = location or click.prompt("Location", default="office")
    resolved_local_ip = local_ip or click.prompt("Local IP address", default="192.168.0.120")
    resolved_github_repo = github_repo or click.prompt("GitHub repository (org/repo)")
    resolved_network_mode = network_mode or click.prompt("Network mode (nat/bridge)", default="nat")

    return HypervisorConfig(
        name=name,
        platform=resolved_platform,
        location=resolved_location,
        local_ip=resolved_local_ip,
        github_repo=resolved_github_repo,
        network_mode=resolved_network_mode,
    )

