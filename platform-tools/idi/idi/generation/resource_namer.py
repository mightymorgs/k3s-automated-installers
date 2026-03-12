"""Resource naming logic for the skill generation pipeline.

Builds resource names from OpenAPI paths, handles compound disambiguation
for nested paths that would otherwise collide, and strips API version
prefixes.  All functions are stateless (or operate on ``GeneratorContext``
caches) -- no class instances required.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Set

from idi.generation.constants import REST_ACTION_SUFFIXES
from idi.generation.context import GeneratorContext
from idi.generation.utils import sanitize_name


# ── Version prefix patterns ──────────────────────────────────────────

# Ordered longest-first so ``api-v3-`` is tried before ``api-``.
_VERSION_PREFIXES: List[str] = [
    "api-v1-", "api-v2-", "api-v3-", "api-v4-",
    "v1-", "v2-", "v3-", "v4-",
    "api-",
]


# ── Public API ────────────────────────────────────────────────────────


def detect_ambiguous_leaves(ctx: GeneratorContext) -> Set[str]:
    """Detect leaf resource names that appear under multiple parent paths.

    Uses a two-pass approach: first collect all leaf-to-parent mappings,
    then return the set of leaf names that are ambiguous (more than one
    distinct parent).  The result is cached on
    ``ctx.ambiguous_leaves_cache`` so repeated calls are free.

    Args:
        ctx: Generator context containing the parsed OpenAPI schema.

    Returns:
        Set of ambiguous leaf names (e.g., ``{'instances', 'bindings'}``).
    """
    if ctx.ambiguous_leaves_cache is not None:
        return ctx.ambiguous_leaves_cache

    leaf_parents: Dict[str, Set[tuple]] = defaultdict(set)

    for path in ctx.schema.get("paths", {}):
        parts = path.strip("/").split("/")
        non_param = [p for p in parts if p and not p.startswith("{")]
        if not non_param:
            continue

        # Strip action suffixes to find the true resource leaf,
        # but never strip down to only version/api prefixes.
        _VS = {"api", "apis", "v1", "v2", "v3", "v4"}
        while len(non_param) > 1 and non_param[-1] in REST_ACTION_SUFFIXES:
            remaining = non_param[:-1]
            if all(s.lower() in _VS for s in remaining):
                break
            non_param = remaining

        leaf = sanitize_name(non_param[-1])
        parent_path = tuple(non_param[:-1]) if len(non_param) > 1 else ()
        leaf_parents[leaf].add(parent_path)

    ctx.ambiguous_leaves_cache = {
        leaf for leaf, parents in leaf_parents.items() if len(parents) > 1
    }
    return ctx.ambiguous_leaves_cache


def build_resource_name(ctx: GeneratorContext, path: str) -> str:
    """Build a resource name from a REST API path.

    For unambiguous leaf names (e.g., ``/core/applications/``), returns
    just the leaf: ``'applications'``.

    For ambiguous leaf names (e.g., ``/outposts/instances/`` vs
    ``/flows/instances/``), joins parent segments with the leaf:
    ``'outposts-instances'`` vs ``'flows-instances'``.

    Action suffixes like ``/used_by``, ``/health``, ``/check_access`` are
    stripped so they group with their parent resource.

    Args:
        ctx: Generator context (used to resolve ambiguous leaves).
        path: REST API path (e.g., ``'/api/v2beta/flows/instances/{id}'``).

    Returns:
        Sanitised resource name string.
    """
    parts = path.strip("/").split("/")
    non_param = [p for p in parts if p and not p.startswith("{")]
    if not non_param:
        return "resource"

    # Strip action suffixes from the end, but never strip down to
    # only version/api prefixes (that would lose the resource name).
    _VERSION_SEGMENTS = {"api", "apis", "v1", "v2", "v3", "v4"}
    while len(non_param) > 1 and non_param[-1] in REST_ACTION_SUFFIXES:
        remaining = non_param[:-1]
        # Guard: don't strip if all remaining segments are version/api prefixes.
        if all(s.lower() in _VERSION_SEGMENTS for s in remaining):
            break
        non_param = remaining

    leaf = sanitize_name(non_param[-1])
    ambiguous = detect_ambiguous_leaves(ctx)

    if leaf in ambiguous and len(non_param) > 1:
        # Use compound name: join all non-param segments.
        return sanitize_name("-".join(non_param))
    return leaf


def extract_known_resources(ctx: GeneratorContext) -> Set[str]:
    """Extract all known resource names from the spec.

    Iterates over every path in the OpenAPI schema and collects unique
    resource names using :func:`build_resource_name` for REST-style APIs.
    The result is cached on ``ctx.known_resources_cache``.

    Note:
        For ``aws`` and ``kubernetes`` styles the extraction is delegated
        to the respective adapter via ``ctx.adapter``.  This function
        only handles the REST path -- callers needing AWS/K8s resource
        names should use the adapter directly.

    Args:
        ctx: Generator context with schema and style information.

    Returns:
        Set of unique resource names found in the spec.
    """
    if ctx.known_resources_cache is not None:
        return ctx.known_resources_cache

    resources: Set[str] = set()
    paths = ctx.schema.get("paths", {})

    for path in paths:
        if ctx.style in ("aws", "kubernetes"):
            # Delegate to adapter for non-REST styles.
            # The adapter's extract_operation() returns an op dict with
            # a ``resource`` key.  We call it with a dummy POST method
            # just to get the resource name.
            methods = paths[path]
            for method in methods:
                op_info = ctx.adapter.extract_operation(
                    path, method, methods[method],
                )
                if op_info and op_info.get("resource"):
                    resources.add(op_info["resource"])
        else:
            # REST uses build_resource_name with disambiguation.
            resource = build_resource_name(ctx, path)
            if resource and resource != "resource":
                resources.add(resource)

    ctx.known_resources_cache = resources
    return ctx.known_resources_cache


def strip_api_version_prefix(resource_name: str) -> str:
    """Strip common API version prefixes from resource names.

    Many ``*arr`` services (Sonarr, Radarr, Prowlarr) use versioned API
    paths like ``/api/v3/qualityprofile``.  These create compound names
    like ``'api-v3-qualityprofile'`` but field inference produces just
    ``'qualityprofile'``.  This helper strips version prefixes to enable
    matching.

    Args:
        resource_name: Resource name that might have a version prefix.

    Returns:
        Resource name with version prefix stripped, or the original if
        no recognised prefix is found.

    Examples:
        >>> strip_api_version_prefix("api-v3-qualityprofile")
        'qualityprofile'
        >>> strip_api_version_prefix("api-v1-indexer")
        'indexer'
        >>> strip_api_version_prefix("v2-endpoint")
        'endpoint'
        >>> strip_api_version_prefix("qualityprofile")
        'qualityprofile'
    """
    for prefix in _VERSION_PREFIXES:
        if resource_name.startswith(prefix):
            return resource_name[len(prefix):]
    return resource_name
