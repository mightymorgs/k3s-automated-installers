"""Tailscale OAuth token exchange."""

from __future__ import annotations

import time

import httpx

from vm_builder.core.hypervisor_service_parts.constants import TAILSCALE_API


def get_tailscale_access_token(self, oauth_id: str, oauth_secret: str) -> str:
    """Exchange OAuth client credentials for a short-lived access token."""
    start = time.monotonic()
    response = httpx.post(
        f"{TAILSCALE_API}/oauth/token",
        auth=(oauth_id, oauth_secret),
        data={"grant_type": "client_credentials", "scope": "all"},
        timeout=30,
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    response.raise_for_status()

    if self._audit:
        self._audit.log_httpx_call(
            method="POST",
            url=f"{TAILSCALE_API}/oauth/token",
            status_code=response.status_code,
            headers={"Authorization": f"Basic {oauth_id}:<secret>"},
            duration_ms=duration_ms,
        )

    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Tailscale OAuth token exchange returned no access_token")
    return token
