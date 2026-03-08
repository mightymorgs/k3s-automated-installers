"""Hypervisor phase0 workflow dispatch operation."""

from __future__ import annotations

import httpx

from vm_builder import bws
from vm_builder.bws import BWSError
from vm_builder.core.hypervisor_service_parts.constants import GITHUB_API


def trigger_phase0(self, hypervisor_name: str, force_reinstall: bool = False) -> dict:
    """Trigger the hypervisor phase0 workflow via workflow_dispatch."""
    github_pat = bws.get_secret("inventory/shared/secrets/github/pat")

    inventory_key = f"inventory/hypervisors/{hypervisor_name}"
    try:
        inventory = bws.get_secret(inventory_key)
        if isinstance(inventory, dict):
            repo = inventory.get("github", {}).get("repo", "")
        else:
            raise RuntimeError(
                f"Hypervisor inventory at {inventory_key} is not valid JSON"
            )
    except BWSError:
        raise RuntimeError(
            f"Hypervisor inventory not found: {inventory_key}. "
            "Run bootstrap first to create the inventory entry."
        )

    if not repo:
        raise RuntimeError(f"No github.repo found in hypervisor inventory: {inventory_key}")

    response = httpx.post(
        f"{GITHUB_API}/repos/{repo}/actions/workflows/install-phase0-hypervisor-setup.yml/dispatches",
        headers={
            "Authorization": f"Bearer {github_pat}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "ref": "main",
            "inputs": {
                "hypervisor_name": hypervisor_name,
                "force_reinstall": str(force_reinstall).lower(),
            },
        },
        timeout=30,
    )

    if self._audit:
        self._audit.log_httpx_call(
            method="POST",
            url=(
                f"{GITHUB_API}/repos/{repo}/actions/workflows/"
                "install-phase0-hypervisor-setup.yml/dispatches"
            ),
            status_code=response.status_code,
            headers={"Authorization": "Bearer <redacted>"},
        )

    if response.status_code == 204:
        return {
            "triggered": True,
            "repo": repo,
            "workflow": "install-phase0-hypervisor-setup.yml",
            "hypervisor_name": hypervisor_name,
            "inventory_key": inventory_key,
            "force_reinstall": force_reinstall,
        }

    raise RuntimeError(
        f"Workflow dispatch failed (HTTP {response.status_code}): {response.text}"
    )
