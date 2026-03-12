"""GitHub API adapter — alias resolution only.

Vendor-specific FK detection, output extraction, and path parameter
classification have been replaced by generic detectors (sections 01-07).

This adapter retains only GITHUB_ALIASES and GitHubFactRef for
node_id->id, login->name, full_name->name canonical field resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set

from idi.generation.adapters.openapi_rest import OpenApiRestAdapter
from idi.generation.fact_model import FactRef, ID_ALIASES

# GitHub-specific aliases — field name to canonical name
GITHUB_ALIASES: Dict[str, str] = {
    "node_id": "id",
    "login": "name",
    "full_name": "name",
}


@dataclass(frozen=True)
class GitHubFactRef(FactRef):
    """FactRef subclass that handles GitHub-specific aliases.

    Maps node_id -> id and login -> name for canonical field resolution.
    """

    def __post_init__(self):
        field_lower = self.field.lower()
        if field_lower in GITHUB_ALIASES:
            canonical = GITHUB_ALIASES[field_lower]
        elif field_lower in ID_ALIASES:
            canonical = "id"
        else:
            canonical = field_lower
        object.__setattr__(self, "canonical_field", canonical)


class GitHubOpenApiAdapter(OpenApiRestAdapter):
    """Adapter for GitHub's pseudo-OpenAPI spec.

    Extends OpenApiRestAdapter. All vendor-specific detection methods
    have been removed; the base adapter handles FK detection via generic
    algorithms. GitHubFactRef provides alias resolution for output facts.
    """

    def __init__(self, service: str = "github", known_resources: Optional[Set[str]] = None):
        super().__init__(service=service, known_resources=known_resources)
