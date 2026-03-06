"""Network-shares list operation for StorageService."""

from __future__ import annotations


def list_network_shares(self, location: str) -> dict:
    """List network shares for a physical location."""
    data = self._bws_get_network_shares(location)
    if data is None:
        return {"location": location, "shares": []}
    return data
