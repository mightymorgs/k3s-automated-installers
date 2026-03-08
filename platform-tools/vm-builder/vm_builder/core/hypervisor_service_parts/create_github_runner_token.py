"""GitHub runner registration token generation."""

from __future__ import annotations

import logging
import time

import httpx

from vm_builder.core.hypervisor_service_parts.constants import GITHUB_API

logger = logging.getLogger(__name__)


def create_github_runner_token(
    self,
    repo: str,
    pat: str,
    runner_name: str,
) -> tuple[str, bool]:
    """Generate a 1-hour GitHub Actions runner registration token."""
    github_headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
    }
    runner_cleaned = False

    response = httpx.get(
        f"{GITHUB_API}/repos/{repo}/actions/runners",
        headers=github_headers,
        timeout=30,
    )
    response.raise_for_status()

    if self._audit:
        self._audit.log_httpx_call(
            method="GET",
            url=f"{GITHUB_API}/repos/{repo}/actions/runners",
            status_code=response.status_code,
            headers={"Authorization": "Bearer <redacted>"},
        )

    runners = response.json().get("runners", [])
    for runner in runners:
        if runner.get("name") == runner_name:
            runner_id = runner["id"]
            logger.info("Deleting stale GitHub runner %s (%s)", runner_id, runner_name)
            httpx.delete(
                f"{GITHUB_API}/repos/{repo}/actions/runners/{runner_id}",
                headers=github_headers,
                timeout=30,
            )
            if self._audit:
                self._audit.log_httpx_call(
                    method="DELETE",
                    url=f"{GITHUB_API}/repos/{repo}/actions/runners/{runner_id}",
                    status_code=200,
                    headers={"Authorization": "Bearer <redacted>"},
                )
            runner_cleaned = True
            time.sleep(2)
            break

    response = httpx.post(
        f"{GITHUB_API}/repos/{repo}/actions/runners/registration-token",
        headers=github_headers,
        timeout=30,
    )
    response.raise_for_status()

    if self._audit:
        self._audit.log_httpx_call(
            method="POST",
            url=f"{GITHUB_API}/repos/{repo}/actions/runners/registration-token",
            status_code=response.status_code,
            headers={"Authorization": "Bearer <redacted>"},
        )

    registration_token = response.json().get("token")
    if not registration_token:
        raise RuntimeError(f"GitHub runner token generation failed: {response.text}")

    return registration_token, runner_cleaned
