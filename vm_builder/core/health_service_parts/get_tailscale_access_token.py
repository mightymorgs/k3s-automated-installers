"""OAuth token exchange for Tailscale API calls."""

from __future__ import annotations

import time

import httpx

from vm_builder.core.health_service_parts.constants import TAILSCALE_API

# Module-level token cache (OAuth tokens are valid for ~1 hour)
_cached_token: str | None = None
_cached_at: float = 0.0
_TOKEN_TTL = 300.0  # Re-fetch every 5 minutes


def get_tailscale_access_token(self, oauth_id: str, oauth_secret: str) -> str:
    """Exchange OAuth client credentials for short-lived access token.

    Caches the token for 5 minutes to avoid repeated OAuth handshakes.
    """
    global _cached_token, _cached_at

    if _cached_token and (time.monotonic() - _cached_at) < _TOKEN_TTL:
        return _cached_token

    response = httpx.post(
        f"{TAILSCALE_API}/oauth/token",
        auth=(oauth_id, oauth_secret),
        data={"grant_type": "client_credentials", "scope": "all"},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Tailscale OAuth token exchange returned no access_token")

    _cached_token = token
    _cached_at = time.monotonic()
    return token
