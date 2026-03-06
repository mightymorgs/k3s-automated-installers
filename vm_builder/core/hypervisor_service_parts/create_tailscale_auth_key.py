"""Tailscale auth key generation."""

from __future__ import annotations

import logging
import time

import httpx

from vm_builder.core.hypervisor_service_parts.constants import TAILSCALE_API

logger = logging.getLogger(__name__)


def create_tailscale_auth_key(
    self,
    hostname: str,
    oauth_id: str,
    oauth_secret: str,
    tags: list[str],
) -> tuple[str, bool]:
    """Create a single-use, pre-authorized Tailscale auth key."""
    access_token = self._get_tailscale_access_token(oauth_id, oauth_secret)
    headers = {"Authorization": f"Bearer {access_token}"}
    device_cleaned = False

    response = httpx.get(
        f"{TAILSCALE_API}/tailnet/-/devices",
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()

    if self._audit:
        self._audit.log_httpx_call(
            method="GET",
            url=f"{TAILSCALE_API}/tailnet/-/devices",
            status_code=response.status_code,
            headers={"Authorization": "Bearer <redacted>"},
        )

    devices = response.json().get("devices", [])

    for device in devices:
        device_hostname = device.get("hostname", "")
        dns_name = device.get("dnsName", "")
        if device_hostname == hostname or dns_name.startswith(f"{hostname}."):
            device_id = device["id"]
            logger.info("Deleting stale Tailscale device %s (%s)", device_id, device_hostname)
            httpx.delete(
                f"{TAILSCALE_API}/device/{device_id}",
                headers=headers,
                timeout=30,
            )
            if self._audit:
                self._audit.log_httpx_call(
                    method="DELETE",
                    url=f"{TAILSCALE_API}/device/{device_id}",
                    status_code=200,
                    headers={"Authorization": "Bearer <redacted>"},
                )
            device_cleaned = True

    if device_cleaned:
        time.sleep(2)

    payload = {
        "capabilities": {
            "devices": {
                "create": {
                    "reusable": False,
                    "ephemeral": False,
                    "preauthorized": True,
                    "tags": tags,
                }
            }
        },
        "expirySeconds": 3600,
    }
    response = httpx.post(
        f"{TAILSCALE_API}/tailnet/-/keys",
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    auth_key = response.json().get("key")
    if not auth_key:
        raise RuntimeError(f"Tailscale auth key creation failed: {response.text}")

    if self._audit:
        self._audit.log_httpx_call(
            method="POST",
            url=f"{TAILSCALE_API}/tailnet/-/keys",
            status_code=response.status_code,
            headers={"Authorization": "Bearer <redacted>"},
            response_body={"key": auth_key},
        )

    return auth_key, device_cleaned
