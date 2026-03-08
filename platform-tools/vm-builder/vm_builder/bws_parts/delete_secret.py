"""Delete-secret operation for BWS CLI wrapper."""

from __future__ import annotations


def delete_secret(secret_id: str) -> None:
    """Delete a BWS secret by UUID."""
    from vm_builder import bws as bws_mod

    start = bws_mod.time.monotonic()
    try:
        bws_mod.subprocess.run(
            ["bws", "secret", "delete", secret_id],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✓ Deleted secret: {secret_id}")
        from vm_builder.bws_parts.cache import get_cache
        get_cache().invalidate()
    except bws_mod.subprocess.CalledProcessError as exc:
        raise bws_mod.BWSError(f"Failed to delete secret '{secret_id}': {exc.stderr}")
    finally:
        duration_ms = int((bws_mod.time.monotonic() - start) * 1000)
        audit_logger = bws_mod.get_audit_logger()
        if audit_logger:
            audit_logger.log_bws_write("delete", secret_id, duration_ms=duration_ms)
