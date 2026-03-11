"""Cloudflare API adapter — resource name normalization only.

Envelope unwrapping is handled by the generic envelope detector
(adapters/envelope_detector.py). allOf flattening is handled by
canonicalize_composed_schema() in field_extractor.py.

This adapter retains only normalize_resource_name() because Cloudflare's
deeply nested path structure requires specialized logic to extract
meaningful resource names.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Set

from .openapi_rest import OpenApiRestAdapter


class CloudflareAdapter(OpenApiRestAdapter):
    """Adapter for Cloudflare API specs.

    Extends OpenApiRestAdapter with resource name normalization
    for deeply nested Cloudflare paths.
    """

    def __init__(
        self,
        service: str,
        known_resources: Optional[Set[str]] = None,
        spec: Optional[Dict[str, Any]] = None,  # accepted for API compat with AdapterRegistry
    ):
        super().__init__(service=service, known_resources=known_resources)

    def normalize_resource_name(self, path: str) -> str:
        """Normalize resource names from deeply nested Cloudflare paths.

        Cloudflare paths can be deeply nested:
            /accounts/{account_id}/access/apps/{app_id}
            /zones/{zone_id}/dns_records/{dns_record_id}

        Strategy: Use the last 1-2 meaningful (non-parameter) path segments,
        joined with hyphens. Underscores are converted to hyphens.

        Args:
            path: API path

        Returns:
            Normalized resource name (e.g., 'access-apps', 'dns-records')
        """
        path_clean = re.sub(r"\{[^}]+\}", "", path)
        parts = [p.replace("_", "-") for p in path_clean.split("/") if p]

        if len(parts) >= 2:
            return "-".join(parts[-2:])
        elif len(parts) == 1:
            return parts[0]
        return "unknown"
