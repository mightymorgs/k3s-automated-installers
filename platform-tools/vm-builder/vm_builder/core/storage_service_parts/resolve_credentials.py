"""Network-share credentials resolver for StorageService."""

from __future__ import annotations

from typing import Optional


def resolve_credentials(self, location: str, share_id: str) -> Optional[dict]:
    """Resolve credentials for a share from its location's BWS secret."""
    data = self._bws_get_network_shares(location)
    if data is None:
        return None

    for share in data.get("shares", []):
        if share.get("id") == share_id:
            return share.get("credentials")

    return None
