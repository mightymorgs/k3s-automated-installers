"""Resource name extraction for the skill generation pipeline.

Provides :func:`get_all_resource_names` which enumerates resource
directory names from an OpenAPI spec, using compound naming for
ambiguous paths (e.g., ``outposts-instances``).

All functions are stateless module-level callables that operate on
:class:`GeneratorContext` caches -- no class instances required.
"""

from __future__ import annotations

import logging
from typing import Set

from idi.generation.context import GeneratorContext
from idi.generation.resource_namer import build_resource_name

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_all_resource_names(
    ctx: GeneratorContext,
    include_non_post: bool = False,
) -> Set[str]:
    """Get all resource names from the spec, optionally restricted to creatable ones.

    Uses :func:`build_resource_name` from ``resource_namer`` to get the
    actual resource directory names, including compound names like
    ``outposts-instances`` for ambiguous paths.  By default, only
    includes resources that have a POST operation (i.e., create skill).

    Results are cached on ``ctx.all_resource_names_cache`` (POST-only)
    or ``ctx.all_resource_names_with_non_post_cache`` (all methods).

    Args:
        ctx: Generator context with schema information.
        include_non_post: If ``True``, include resources without POST
            operations.  Useful for dependency resolution where the
            target might be a read-only resource.

    Returns:
        Set of resource name strings (e.g.,
        ``{'applications', 'providers-oauth2', 'flows-instances'}``).
    """
    if include_non_post:
        if ctx.all_resource_names_with_non_post_cache is not None:
            return ctx.all_resource_names_with_non_post_cache
    else:
        if ctx.all_resource_names_cache is not None:
            return ctx.all_resource_names_cache

    resources: Set[str] = set()
    paths = ctx.schema.get("paths", {})

    for path in paths:
        methods = paths[path]
        if not isinstance(methods, dict):
            continue
        # Include resources that have POST operation OR (if include_non_post)
        # any operation.
        if not include_non_post and "post" not in methods:
            continue

        if ctx.style == "kubernetes":
            # K8s paths: take last non-param segment (matches extract_k8s_operation).
            # This avoids compound naming from ambiguous leaves caused by
            # cluster-scoped vs namespaced paths for the same resource.
            parts = path.strip("/").split("/")
            non_param = [p for p in parts if p and not p.startswith("{")]
            resource_name = non_param[-1] if non_param else ""
            # Skip status subresource.
            if resource_name == "status":
                continue
        else:
            resource_name = build_resource_name(ctx, path)

        if resource_name and resource_name != "resource":
            resources.add(resource_name)

    if include_non_post:
        ctx.all_resource_names_with_non_post_cache = resources
    else:
        ctx.all_resource_names_cache = resources

    return resources


