"""Load and inspect OpenAPI specifications for skill generation.

Handles:
- Loading specs from local files or URLs (JSON and YAML), with all
  ``$ref`` pointers resolved at load time via a built-in recursive resolver.
- Deriving API service names from spec ``info.title``.
- Auto-detecting the API style (rest, aws, kubernetes, etc.).
- Constructing a fully-initialised :class:`GeneratorContext`.

All functions are stateless module-level callables -- no ``self``.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.error import URLError
from urllib.request import urlopen

import yaml

from idi.generation.adapters import _registry, get_adapter
from idi.generation.context import GeneratorContext

logger = logging.getLogger(__name__)

def _follow_ref(spec: Dict[str, Any], ref_str: str) -> Dict[str, Any]:
    """Follow a JSON Pointer like ``#/components/schemas/Foo``.

    Args:
        spec: The root spec dictionary.
        ref_str: A JSON Pointer string.

    Returns:
        The referenced schema dict, or ``{}`` if the path doesn't exist.
    """
    parts = ref_str.lstrip("#/").split("/")
    result: Any = spec
    for part in parts:
        if isinstance(result, dict) and part in result:
            result = result[part]
        else:
            return {}
    return result


def _resolve_refs(
    obj: Any,
    spec: Dict[str, Any],
    seen: Optional[Set[str]] = None,
    depth: int = 0,
    max_depth: int = 30,
    memo: Optional[Dict[str, Any]] = None,
) -> Any:
    """Resolve all internal ``$ref`` pointers recursively.

    Handles circular references via a *seen* set and guards against
    infinite recursion with a *max_depth* limit.  A *memo* cache avoids
    redundant resolution of the same ``$ref`` path.

    Args:
        obj: The current object (dict, list, or scalar) to resolve.
        spec: The root spec dictionary (for following ``$ref`` paths).
        seen: Set of already-visited ``$ref`` strings (cycle detection).
        depth: Current recursion depth.
        max_depth: Maximum recursion depth before returning ``{}``.
        memo: Cache of already-resolved ``$ref`` paths.

    Returns:
        A new object with all ``$ref`` pointers replaced by their targets.
    """
    if depth > max_depth:
        return {}
    if seen is None:
        seen = set()
    if memo is None:
        memo = {}
    if isinstance(obj, dict):
        if "$ref" in obj and len(obj) == 1:
            ref = obj["$ref"]
            if ref in seen:
                return {}
            if ref in memo:
                return copy.deepcopy(memo[ref])
            seen = seen | {ref}
            target = _follow_ref(spec, ref)
            resolved = _resolve_refs(
                copy.deepcopy(target), spec, seen, depth + 1, max_depth, memo,
            )
            memo[ref] = resolved
            return resolved
        return {
            k: _resolve_refs(v, spec, seen, depth + 1, max_depth, memo)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [
            _resolve_refs(v, spec, seen, depth + 1, max_depth, memo)
            for v in obj
        ]
    return obj


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def load_spec(
    schema_path: str,
    *,
    resolve_refs: bool = True,
) -> Dict[str, Any]:
    """Load and parse an OpenAPI spec from a file path or URL.

    When *resolve_refs* is ``True`` (the default), all ``$ref`` pointers
    are resolved at load time via :func:`_resolve_refs`.

    Args:
        schema_path: Local file path or ``http(s)://`` URL to the spec.
        resolve_refs: If ``True``, resolve all ``$ref`` pointers.

    Returns:
        Parsed specification as a dictionary.

    Raises:
        RuntimeError: If a URL fetch fails.
        FileNotFoundError: If a local path does not exist.
    """
    if schema_path.startswith(("http://", "https://")):
        logger.info("Fetching schema from %s ...", schema_path)
        try:
            with urlopen(schema_path) as response:  # noqa: S310
                content = response.read().decode("utf-8")
        except URLError as exc:
            raise RuntimeError(f"Failed to fetch schema: {exc}") from exc
    else:
        logger.info("Loading schema from %s ...", schema_path)
        path = Path(schema_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        content = path.read_text(encoding="utf-8")

    # Try JSON first (faster, no tag issues).
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        # Fall back to YAML with a custom constructor for the ``value`` tag
        # that some specs emit.
        loader = yaml.SafeLoader
        loader.add_constructor(
            "tag:yaml.org,2002:value",
            lambda loader, node: loader.construct_scalar(node),
        )
        raw = yaml.load(content, Loader=loader)  # noqa: S506

    if not resolve_refs:
        return raw

    resolved = copy.deepcopy(raw)
    memo: Dict[str, Any] = {}  # Shared cache across all sections
    for section in ("paths", "components", "definitions"):
        if section in resolved:
            resolved[section] = _resolve_refs(resolved[section], raw, memo=memo)
    return resolved


# ---------------------------------------------------------------------------
# Schema name normalization
# ---------------------------------------------------------------------------

_SCHEMA_SUFFIXES = ("Response", "Output", "Input", "Request", "DTO", "Dto", "Model", "Schema", "Resource")
_SCHEMA_PREFIXES = ("Create", "Update", "Patch")


def normalize_schema_name(name: str) -> str:
    """Strip common suffixes/prefixes from a schema name for resource matching.

    Attempts suffix stripping first, then prefix stripping if no suffix matched.
    Guards against producing empty or very short names (<=2 chars).
    """
    # Try suffix stripping first
    for suffix in _SCHEMA_SUFFIXES:
        if name.endswith(suffix):
            candidate = name[: -len(suffix)]
            if len(candidate) > 2:
                return candidate
            return name

    # Try prefix stripping
    for prefix in _SCHEMA_PREFIXES:
        if name.startswith(prefix):
            candidate = name[len(prefix) :]
            if len(candidate) > 2:
                return candidate
            return name

    return name


# ---------------------------------------------------------------------------
# Name and style derivation
# ---------------------------------------------------------------------------

def derive_api_name(schema: Dict[str, Any]) -> str:
    """Derive a service name from the spec's ``info.title``.

    The title is lower-cased, non-alphanumeric runs are collapsed to
    hyphens, and the result is truncated to 30 characters.

    Args:
        schema: Parsed OpenAPI specification dict.

    Returns:
        Sanitised service name (e.g. ``'authentik'``).
    """
    info = schema.get("info", {})
    title = info.get("title", "api")
    name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return name[:30]


def detect_style(api_name: str, schema: Dict[str, Any]) -> str:
    """Detect the API style from spec paths and metadata.

    Delegates to the adapter registry's detection logic which inspects
    service name, spec structure, and URL path patterns in order.

    Args:
        api_name: Service name (used for name-based matching).
        schema: Parsed OpenAPI specification dict.

    Returns:
        Style string: ``'rest'``, ``'aws'``, ``'kubernetes'``,
        ``'cloudflare'``, ``'vault'``, ``'github'``, etc.
    """
    paths = list(schema.get("paths", {}).keys())
    if not paths:
        return "rest"

    sample = paths[0]
    return _registry.detect_style(sample, service=api_name, spec=schema)


# ---------------------------------------------------------------------------
# Known-resource extraction (lightweight, for adapter init)
# ---------------------------------------------------------------------------

def _extract_known_resources_simple(
    schema: Dict[str, Any],
    style: str,
) -> Set[str]:
    """Extract a quick set of resource names from path segments.

    This is a lightweight helper used only for adapter initialisation.
    The full, disambiguation-aware resource naming lives in the
    ``resource_namer`` module.

    Args:
        schema: Parsed OpenAPI spec dict.
        style: Detected API style.

    Returns:
        Set of resource name strings.
    """
    resources: Set[str] = set()
    for path in schema.get("paths", {}):
        segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
        if not segments:
            continue
        # Use the last non-parameter segment as a rough resource name.
        candidate = segments[-1].lower()
        if candidate and candidate != "resource":
            resources.add(candidate)
    return resources


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_context(
    schema_path: str,
    output_dir: str,
    api_name: Optional[str] = None,
    style: str = "auto",
) -> GeneratorContext:
    """Create a fully initialised :class:`GeneratorContext` from a spec path.

    Loads the spec, derives the service name and API style (unless
    overridden), creates the appropriate schema adapter, and returns a
    ready-to-use context object.

    Args:
        schema_path: Path or URL to the OpenAPI spec file.
        output_dir: Root directory for generated skill JSON output.
        api_name: Explicit service name.  If ``None``, derived from the
            spec's ``info.title``.
        style: API style override.  ``'auto'`` triggers detection.

    Returns:
        Populated :class:`GeneratorContext`.
    """
    schema = load_spec(schema_path)
    name = api_name or derive_api_name(schema)
    resolved_style = style if style != "auto" else detect_style(name, schema)

    known_resources = _extract_known_resources_simple(schema, resolved_style)
    sample_path = next(iter(schema.get("paths", {}).keys()), None)

    adapter = get_adapter(
        service=name,
        style=resolved_style,
        sample_path=sample_path,
        known_resources=known_resources,
        spec=schema,
    )

    return GeneratorContext(
        schema=schema,
        api_name=name,
        style=resolved_style,
        adapter=adapter,
        output_dir=Path(output_dir),
    )
