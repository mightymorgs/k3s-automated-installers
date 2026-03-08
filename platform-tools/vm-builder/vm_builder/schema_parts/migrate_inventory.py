"""Schema migration helper for inventory documents."""

from __future__ import annotations


def migrate_inventory(data: dict) -> dict:
    """Migrate inventory to latest schema version (v3.3)."""
    version = data.get("schema_version", "v3.1")

    if version == "v3.1":
        data = {**data}
        data["schema_version"] = "v3.2"
        data["ingress"] = data.get(
            "ingress",
            {
                "mode": "nodeport",
                "sso_overrides": {},
            },
        )
        version = "v3.2"

    if version == "v3.2":
        data = {**data}
        data["schema_version"] = "v3.3"
        data["storage"] = data.get(
            "storage",
            {
                "location": "",
                "mounts": [],
                "app_paths": {},
            },
        )

    return data
