"""Ingress validation helper for VM service."""

from __future__ import annotations

from typing import Optional

from vm_builder.core.models import IngressValidateResult
from vm_builder.core.vm_service_parts.constants import DOMAIN_RE, VALID_INGRESS_MODES


def validate_ingress(
    self,
    mode: str,
    domain: Optional[str] = None,
    app_overrides: Optional[dict[str, str]] = None,
) -> IngressValidateResult:
    """Validate ingress configuration before VM creation."""
    warnings: list[str] = []

    if mode not in VALID_INGRESS_MODES:
        return IngressValidateResult(
            valid=False,
            error=f"Unknown ingress mode: {mode}. Must be one of: "
            f"{', '.join(sorted(VALID_INGRESS_MODES))}",
        )

    # Validate per-app overrides
    needs_domain = mode == "cloudflare"
    for app_id, app_mode in (app_overrides or {}).items():
        if app_mode not in VALID_INGRESS_MODES:
            return IngressValidateResult(
                valid=False,
                error=f"Invalid ingress mode '{app_mode}' for app '{app_id}'. "
                f"Must be one of: {', '.join(sorted(VALID_INGRESS_MODES))}",
            )
        if app_mode == "cloudflare":
            needs_domain = True

    if needs_domain:
        if not domain:
            return IngressValidateResult(
                valid=False,
                error="Cloudflare mode requires a domain (set by default or per-app override)",
            )
        if not DOMAIN_RE.match(domain):
            return IngressValidateResult(
                valid=False,
                error=f"Invalid domain format: {domain}",
            )

    return IngressValidateResult(valid=True, warnings=warnings)
