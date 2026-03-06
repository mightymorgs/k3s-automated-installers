"""Interactive prompts for init command."""

from __future__ import annotations

from typing import Any

import click

from vm_builder.core.models import (
    AnsibleSecrets,
    CloudflareSecrets,
    ConsoleSecrets,
    GitHubSecrets,
    HashiCorpSecrets,
    SharedSecrets,
    TailscaleSecrets,
    TerraformSecrets,
)


def _prompt_tailscale(config: dict[str, Any]) -> TailscaleSecrets:
    click.echo()
    click.echo("-" * 70)
    click.echo("TAILSCALE")
    click.echo("-" * 70)
    return TailscaleSecrets(
        oauthclientid=click.prompt(
            "Tailscale OAuth Client ID",
            default=config.get("tailscale", {}).get("oauthclientid", ""),
            show_default=False,
        ),
        oauthclientsecret=click.prompt(
            "Tailscale OAuth Client Secret",
            default=config.get("tailscale", {}).get("oauthclientsecret", ""),
            show_default=False,
            hide_input=True,
        ),
        tailnet=click.prompt(
            "Tailscale Tailnet",
            default=config.get("tailscale", {}).get("tailnet", ""),
        ),
        apikey=click.prompt(
            "Tailscale API Key",
            default=config.get("tailscale", {}).get("apikey", ""),
            show_default=False,
            hide_input=True,
        ),
    )


def _prompt_terraform(config: dict[str, Any]) -> TerraformSecrets:
    click.echo()
    click.echo("-" * 70)
    click.echo("TERRAFORM CLOUD")
    click.echo("-" * 70)
    return TerraformSecrets(
        cloudtoken=click.prompt(
            "Terraform Cloud Token",
            default=config.get("terraform", {}).get("cloudtoken", ""),
            show_default=False,
            hide_input=True,
        ),
        cloudorganization=click.prompt(
            "Terraform Cloud Organization",
            default=config.get("terraform", {}).get("cloudorganization", ""),
        ),
    )


def _prompt_cloudflare(config: dict[str, Any]) -> CloudflareSecrets:
    click.echo()
    click.echo("-" * 70)
    click.echo("CLOUDFLARE")
    click.echo("-" * 70)
    return CloudflareSecrets(
        apitoken=click.prompt(
            "Cloudflare API Token",
            default=config.get("cloudflare", {}).get("apitoken", ""),
            show_default=False,
            hide_input=True,
        ),
        accountid=click.prompt(
            "Cloudflare Account ID",
            default=config.get("cloudflare", {}).get("accountid", ""),
        ),
        zoneid=click.prompt(
            "Cloudflare Zone ID",
            default=config.get("cloudflare", {}).get("zoneid", ""),
        ),
    )


def _prompt_github(config: dict[str, Any]) -> GitHubSecrets:
    click.echo()
    click.echo("-" * 70)
    click.echo("GITHUB")
    click.echo("-" * 70)
    return GitHubSecrets(
        pat=click.prompt(
            "GitHub PAT (repo + workflow scope)",
            default=config.get("github", {}).get("pat", ""),
            show_default=False,
            hide_input=True,
        ),
        patsecretswrite=click.prompt(
            "GitHub PAT with secrets:write scope",
            default=config.get("github", {}).get("patsecretswrite", ""),
            show_default=False,
            hide_input=True,
        ),
    )


def _prompt_hashicorp(config: dict[str, Any]) -> HashiCorpSecrets | None:
    click.echo()
    click.echo("-" * 70)
    click.echo("HASHICORP CLOUD PLATFORM (optional)")
    click.echo("-" * 70)
    if not click.confirm("Configure HashiCorp Cloud Platform?", default=False):
        return None
    return HashiCorpSecrets(
        cloudprojectid=click.prompt(
            "HCP Project ID",
            default=config.get("hashicorp", {}).get("cloudprojectid", ""),
        ),
        cloudprojectname=click.prompt(
            "HCP Project Name",
            default=config.get("hashicorp", {}).get("cloudprojectname", ""),
        ),
    )


def _prompt_console(config: dict[str, Any]) -> ConsoleSecrets:
    click.echo()
    click.echo("-" * 70)
    click.echo("VM DEFAULTS")
    click.echo("-" * 70)
    return ConsoleSecrets(
        username=click.prompt(
            "Default VM admin username",
            default=config.get("console", {}).get("username", "admin"),
        ),
        password=click.prompt(
            "Default VM admin password",
            default=config.get("console", {}).get("password", ""),
            show_default=False,
            hide_input=True,
            confirmation_prompt=True,
        ),
    )


def _prompt_ansible(config: dict[str, Any]) -> AnsibleSecrets:
    click.echo()
    click.echo("-" * 70)
    click.echo("ANSIBLE")
    click.echo("-" * 70)
    return AnsibleSecrets(
        vaultpassword=click.prompt(
            "Ansible Vault Password",
            default=config.get("ansible", {}).get("vaultpassword", ""),
            show_default=False,
            hide_input=True,
            confirmation_prompt=True,
        )
    )


def collect_shared_secrets(config: dict[str, Any]) -> SharedSecrets:
    """Collect all shared secret fields interactively."""
    return SharedSecrets(
        tailscale=_prompt_tailscale(config),
        terraform=_prompt_terraform(config),
        cloudflare=_prompt_cloudflare(config),
        github=_prompt_github(config),
        hashicorp=_prompt_hashicorp(config),
        console=_prompt_console(config),
        ansible=_prompt_ansible(config),
    )

