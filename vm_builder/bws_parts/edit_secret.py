"""Edit-secret operation for BWS CLI wrapper."""

from __future__ import annotations

import json
from typing import Union


def edit_secret(secret_id: str, new_value: Union[dict, str]) -> None:
    """Edit an existing BWS secret by UUID."""
    from vm_builder import bws as bws_mod

    value_str = json.dumps(new_value) if isinstance(new_value, dict) else new_value

    start = bws_mod.time.monotonic()
    try:
        bws_mod.subprocess.run(
            ["bws", "secret", "edit", secret_id, "--value", value_str],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✓ Updated secret: {secret_id}")
        from vm_builder.bws_parts.cache import get_cache
        get_cache().invalidate_value(secret_id)
    except bws_mod.subprocess.CalledProcessError as exc:
        raise bws_mod.BWSError(f"Failed to edit secret '{secret_id}': {exc.stderr}")
    finally:
        duration_ms = int((bws_mod.time.monotonic() - start) * 1000)
        audit_logger = bws_mod.get_audit_logger()
        if audit_logger:
            audit_logger.log_bws_write("edit", secret_id, value_str, duration_ms)
