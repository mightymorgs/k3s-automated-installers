"""Polling background task for auto-refresh when webhooks are unavailable."""

import asyncio
import logging

logger = logging.getLogger(__name__)


class RefreshPoller:
    """Periodically checks for new commits and triggers refresh.

    Only triggers a refresh if the remote branch has new commits
    (avoids unnecessary git pull + regenerate cycles).

    Set interval_seconds=0 to disable polling entirely.
    """

    def __init__(
        self,
        coordinator,
        repo_service,
        interval_seconds: int = 0,
    ):
        self._coordinator = coordinator
        self._repo_service = repo_service
        self._interval = interval_seconds
        self._running = False

    async def start(self) -> None:
        """Run the polling loop until stop() is called."""
        if self._interval <= 0:
            logger.info("Polling disabled (interval=%d)", self._interval)
            return

        self._running = True
        logger.info("Polling started: interval=%ds", self._interval)

        while self._running:
            try:
                has_new = await asyncio.to_thread(
                    self._repo_service.has_new_commits
                )
                if has_new:
                    logger.info("New commits detected, triggering refresh")
                    result = await self._coordinator.refresh()
                    logger.info("Poll refresh result: %s", result.status)
                else:
                    logger.debug("No new commits")
            except Exception:
                logger.exception("Poll cycle error")

            # Sleep in small increments so stop() is responsive
            for _ in range(int(self._interval * 10)):
                if not self._running:
                    break
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        """Signal the polling loop to stop."""
        self._running = False
        logger.info("Polling stopped")
