"""Shared state container for skill generation.

Replaces the monolithic ``AtomicSkillGenerator.self`` by threading a
single ``GeneratorContext`` dataclass through every module function.
Caches are lazily initialised on first access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Set


@dataclass
class GeneratorContext:
    """Immutable-ish context shared across all generation modules.

    The ``schema``, ``api_name``, ``style``, and ``output_dir`` fields
    are set once at construction.  The cache fields are populated lazily
    by the modules that own them — callers should use the helper
    functions (e.g., ``resource_namer.get_ambiguous_leaves(ctx)``)
    rather than accessing caches directly.

    Attributes:
        schema: Parsed OpenAPI specification dict.
        api_name: Service name (e.g., ``'authentik'``).
        style: Detected API style (``'rest'``, ``'aws'``, ``'kubernetes'``).
        adapter: Schema adapter instance from :func:`get_adapter`.
        output_dir: Root directory for generated skill JSON.
        generated_skill_paths: Map of skill path → metadata, built during
            generation for check_with / dangling-ref validation.
        ambiguous_leaves_cache: Lazily populated by
            :func:`resource_namer.get_ambiguous_leaves`.
        known_resources_cache: Lazily populated by
            :func:`resource_namer.get_known_resources`.
        all_resource_names_cache: Lazily populated by
            :func:`dependency_resolver.get_all_resource_names`.
        resource_op_cache: Maps ``resource → (path, method)`` for
            creatable operations.
    """

    # Core (set once)
    schema: Dict[str, Any]
    api_name: str
    style: str
    adapter: Any
    output_dir: Path

    # Generation tracking
    generated_skill_paths: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Caches (lazily populated by owning modules)
    ambiguous_leaves_cache: Optional[Set[str]] = None
    known_resources_cache: Optional[Set[str]] = None
    all_resource_names_cache: Optional[Set[str]] = None
    all_resource_names_with_non_post_cache: Optional[Set[str]] = None
    resource_op_cache: Optional[Dict[str, Any]] = None
