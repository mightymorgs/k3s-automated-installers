"""Shared-secret write orchestration for InitService."""

from __future__ import annotations

from vm_builder import bws
from vm_builder.core.models import (
    SecretWriteResult,
    SecretWriteStatus,
    SharedSecrets,
)


def write_secrets(
    self,
    secrets: SharedSecrets,
    overwrite: bool = False,
) -> list[SecretWriteResult]:
    """Write shared secrets to BWS (create/update/skip with status tracking)."""
    results: list[SecretWriteResult] = []
    for path, value in secrets.to_bws_dict().items():
        try:
            if bws.secret_exists(path):
                if overwrite:
                    existing = bws.list_secrets(filter_key=path)
                    if existing:
                        bws.edit_secret(existing[0]["id"], value)
                        results.append(
                            SecretWriteResult(
                                path=path,
                                status=SecretWriteStatus.UPDATED,
                            )
                        )
                    else:
                        bws.create_secret(path, value)
                        results.append(
                            SecretWriteResult(
                                path=path,
                                status=SecretWriteStatus.CREATED,
                            )
                        )
                else:
                    results.append(
                        SecretWriteResult(
                            path=path,
                            status=SecretWriteStatus.SKIPPED,
                        )
                    )
            else:
                bws.create_secret(path, value)
                results.append(
                    SecretWriteResult(
                        path=path,
                        status=SecretWriteStatus.CREATED,
                    )
                )
        except (bws.BWSError, Exception) as exc:
            results.append(
                SecretWriteResult(
                    path=path,
                    status=SecretWriteStatus.ERROR,
                    error=str(exc),
                )
            )
    return results
