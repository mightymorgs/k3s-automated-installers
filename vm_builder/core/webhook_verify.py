"""GitHub webhook HMAC-SHA256 signature verification."""

import hashlib
import hmac


class WebhookVerificationError(Exception):
    """Raised when webhook signature verification fails."""


def verify_github_signature(
    body: bytes,
    signature_header: str | None,
    secret: str,
) -> None:
    """Verify a GitHub webhook HMAC-SHA256 signature.

    GitHub signs webhook payloads using HMAC-SHA256 with a shared secret.
    The ``X-Hub-Signature-256`` header contains ``sha256=<hex-digest>``.

    This function uses ``hmac.compare_digest`` for constant-time comparison
    to prevent timing attacks.

    Args:
        body: Raw request body bytes.
        signature_header: Value of X-Hub-Signature-256 header.
        secret: The shared webhook secret.

    Raises:
        WebhookVerificationError: On any verification failure.
    """
    if not secret:
        raise WebhookVerificationError("Webhook secret not configured")

    if not signature_header:
        raise WebhookVerificationError("Missing signature header")

    if not signature_header.startswith("sha256="):
        raise WebhookVerificationError(
            "Invalid signature format: expected 'sha256=<hex>'"
        )

    expected_sig = signature_header[7:]  # Strip "sha256=" prefix
    computed = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed, expected_sig):
        raise WebhookVerificationError("Signature mismatch")
