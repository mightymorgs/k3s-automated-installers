"""Hypervisor bootstrap script generation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Template

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.core.errors import BwsSecretError
from vm_builder.core.models import BootstrapScriptResult, HypervisorConfig


def generate_bootstrap_script(self, config: HypervisorConfig) -> BootstrapScriptResult:
    """Generate bootstrap script from config, fetching secrets from BWS."""
    try:
        tailscale_oauth_id = bws.get_secret("inventory/shared/secrets/tailscale/oauthclientid")
        tailscale_oauth_secret = bws.get_secret(
            "inventory/shared/secrets/tailscale/oauthclientsecret"
        )
        github_pat = bws.get_secret("inventory/shared/secrets/github/pat")
    except BWSError as exc:
        raise BwsSecretError(f"Failed to fetch bootstrap credentials from BWS: {exc}") from exc

    try:
        versions_json = bws.get_secret("inventory/shared/versions")
        versions = (
            json.loads(versions_json)
            if isinstance(versions_json, str)
            else versions_json
        )
        github_runner_version = versions.get("github_runner", "2.332.0")
    except Exception:
        github_runner_version = "2.332.0"

    tags = [
        "tag:hypervisor",
        "tag:vm-host",
        "tag:service-ssh",
        f"tag:hv-{config.name}",
    ]

    tailscale_auth_key, tailscale_cleaned = self._create_tailscale_auth_key(
        hostname=config.full_name,
        oauth_id=tailscale_oauth_id,
        oauth_secret=tailscale_oauth_secret,
        tags=tags,
    )

    runner_name = f"hv-{config.name}"
    github_runner_reg_token, github_cleaned = self._create_github_runner_token(
        repo=config.github_repo,
        pat=github_pat,
        runner_name=runner_name,
    )

    inventory_key = self._create_hypervisor_inventory(config, runner_name)

    template_path = Path(__file__).parent.parent.parent / "templates" / "hypervisor-bootstrap.sh.j2"
    with open(template_path, "r") as file_obj:
        template = Template(file_obj.read())

    script_content = template.render(
        hypervisor_name=config.full_name,
        short_name=config.name,
        platform=config.platform,
        location=config.location,
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        tailscale_auth_key=tailscale_auth_key,
        github_runner_reg_token=github_runner_reg_token,
        github_repo=config.github_repo,
        github_runner_version=github_runner_version,
        vm_builder_api_url=config.vm_builder_api_url or "",
    )

    return BootstrapScriptResult(
        script_content=script_content,
        hypervisor_full_name=config.full_name,
        inventory_key=inventory_key,
        tailscale_device_cleaned=tailscale_cleaned,
        github_runner_cleaned=github_cleaned,
    )
