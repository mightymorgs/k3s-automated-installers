"""Refresh coordinator -- serializes repo pull + registry reload with debounce."""

import asyncio
import time
import logging

from vm_builder.core.models import RefreshResult, RefreshStatus

logger = logging.getLogger(__name__)


class RefreshCoordinator:
    """Coordinates registry refresh with locking and cooldown.

    Ensures only one refresh runs at a time. Requests arriving during
    an active refresh get an ALREADY_IN_PROGRESS response. A cooldown
    window prevents re-refreshing too quickly after a successful refresh.
    """

    def __init__(
        self,
        repo_service,
        registry_service,
        cooldown_seconds: int = 30,
    ):
        self._repo_service = repo_service
        self._registry_service = registry_service
        self._cooldown_seconds = cooldown_seconds
        self._lock = asyncio.Lock()
        self._last_refresh_at: float = 0.0

    async def refresh(self) -> RefreshResult:
        """Attempt a refresh. Returns immediately if locked or in cooldown."""
        # Try to acquire lock without blocking
        if self._lock.locked():
            return RefreshResult(
                status=RefreshStatus.ALREADY_IN_PROGRESS,
                message="A refresh is already running",
            )

        async with self._lock:
            # Check cooldown
            elapsed = time.monotonic() - self._last_refresh_at
            if self._last_refresh_at > 0 and elapsed < self._cooldown_seconds:
                remaining = self._cooldown_seconds - elapsed
                return RefreshResult(
                    status=RefreshStatus.COOLDOWN_ACTIVE,
                    message=(
                        f"Last refresh {elapsed:.0f}s ago, cooldown is "
                        f"{self._cooldown_seconds}s ({remaining:.0f}s remaining)"
                    ),
                )

            try:
                # Run blocking git operations in thread pool
                commit_sha = await asyncio.to_thread(
                    self._repo_service.refresh_repo
                )
                await asyncio.to_thread(self._registry_service.reload)

                apps = self._registry_service.list_apps()
                self._last_refresh_at = time.monotonic()

                logger.info(
                    "Registry refreshed: commit=%s, apps=%d",
                    commit_sha,
                    len(apps),
                )
                return RefreshResult(
                    status=RefreshStatus.REFRESHED,
                    commit_sha=commit_sha,
                    apps_count=len(apps),
                )
            except Exception as e:
                logger.exception("Refresh failed")
                return RefreshResult(
                    status=RefreshStatus.ERROR,
                    error=str(e),
                )
