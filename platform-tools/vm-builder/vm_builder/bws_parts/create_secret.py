"""Create-secret operation for BWS CLI wrapper."""

from __future__ import annotations

import json
from typing import Optional, Union


def create_secret(
    key: str,
    value: Union[dict, str],
    project_id: Optional[str] = None,
) -> None:
    """Create a secret in BWS under an allowed path."""
    from vm_builder import bws as bws_mod

    bws_mod.check_allowed_write_path(key)
    if project_id is None:
        project_id = bws_mod.get_project_id()
    value_str = json.dumps(value) if isinstance(value, dict) else value

    start = bws_mod.time.monotonic()
    try:
        bws_mod.subprocess.run(
            ["bws", "secret", "create", key, value_str, project_id],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✓ Created: {key}")
        from vm_builder.bws_parts.cache import get_cache
        get_cache().invalidate()
    except bws_mod.subprocess.CalledProcessError as exc:
        raise bws_mod.BWSError(f"Failed to create secret '{key}': {exc.stderr}")
    finally:
        duration_ms = int((bws_mod.time.monotonic() - start) * 1000)
        audit_logger = bws_mod.get_audit_logger()
        if audit_logger:
            audit_logger.log_bws_write("create", key, value_str, duration_ms)
