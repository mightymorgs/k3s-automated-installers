"""GitHub webhook endpoint for auto-refresh on push."""

import os
import logging

from fastapi import APIRouter, Request, Response
from vm_builder.core.webhook_verify import verify_github_signature, WebhookVerificationError
from vm_builder.core.models import RefreshStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhook", tags=["webhook"])

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def get_refresh_coordinator():
    """Get the shared RefreshCoordinator singleton.

    Imported lazily to avoid circular deps. Provided by deps.py.
    """
    from vm_builder.api.deps import get_refresh_coordinator as _get
    return _get()


@router.post("/github")
async def github_webhook(request: Request):
    """Receive GitHub push webhook and trigger registry refresh.

    Validates HMAC-SHA256 signature, filters for push events only,
    and delegates to RefreshCoordinator.

    Returns:
        200: Refresh completed, event ignored, or ping acknowledged.
        202: Refresh already in progress (accepted, will complete).
        403: Signature verification failed.
        501: Webhook secret not configured.
    """
    event = request.headers.get("X-GitHub-Event", "")

    # GitHub sends a ping when the webhook is first configured
    if event == "ping":
        return {"status": "pong"}

    # Check that webhook secret is configured
    if not WEBHOOK_SECRET:
        return Response(
            content='{"error": "Webhook secret not configured"}',
            status_code=501,
            media_type="application/json",
        )

    # Read raw body for signature verification
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    try:
        verify_github_signature(body, signature, WEBHOOK_SECRET)
    except WebhookVerificationError as e:
        logger.warning("Webhook signature verification failed: %s", e)
        return Response(
            content=f'{{"error": "{e}"}}',
            status_code=403,
            media_type="application/json",
        )

    # Only process push events
    if event != "push":
        logger.info("Ignoring non-push webhook event: %s", event)
        return {"status": "ignored", "event": event}

    # Trigger refresh
    coordinator = get_refresh_coordinator()
    result = await coordinator.refresh()

    if result.status == RefreshStatus.ALREADY_IN_PROGRESS:
        return Response(
            content=result.model_dump_json(),
            status_code=202,
            media_type="application/json",
        )

    return result.model_dump()
