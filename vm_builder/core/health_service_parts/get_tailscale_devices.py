"""Tailscale device list fetch for HealthService."""

from __future__ import annotations

import httpx

from vm_builder import bws
from vm_builder.core.health_service_parts.constants import TAILSCALE_API


def get_tailscale_devices(self) -> list[dict]:
    """Fetch all Tailscale devices using BWS-stored OAuth creds."""
    oauth_id = bws.get_secret("inventory/shared/secrets/tailscale/oauthclientid")
    oauth_secret = bws.get_secret(
        "inventory/shared/secrets/tailscale/oauthclientsecret"
    )
    access_token = self._get_tailscale_access_token(oauth_id, oauth_secret)

    response = httpx.get(
        f"{TAILSCALE_API}/tailnet/-/devices?fields=all",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("devices", [])
