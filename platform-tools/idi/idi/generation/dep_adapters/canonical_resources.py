"""Canonical resource alias map derived from OpenAPI path structure.

Parses all path templates to build a mapping from every resource name
variation (composite names, underscored, hyphenated, singular/plural)
to a single canonical form.  Used by identifier index, fan-out
suppression, and other gates for consistent resource lookups.

All signals are derived programmatically from the spec — no hand-crafted
resource lists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from idi.generation.dep_adapters.naming import _engine

_PATH_PARAM_RE = re.compile(r"^\{(\w+)\}$")
_VERSION_SEGMENT_RE = re.compile(r"^v\d+", re.IGNORECASE)
_SKIP_SEGMENTS = frozenset({"api", "apis"})


@dataclass
class _ResourceInfo:
    """Internal storage for a discovered resource."""

    canonical: str
    path_param: str | None = None
    parent: str | None = None
    aliases: set[str] = field(default_factory=set)


class CanonicalResourceMap:
    """Maps resource name variations to canonical forms.

    Built once per spec from :func:`build_canonical_resource_map`.
    All lookups are O(1) dict access.
    """

    def __init__(
        self,
        lookup: dict[str, str],
        resources: dict[str, _ResourceInfo],
    ) -> None:
        self._lookup = lookup        # variation -> canonical name
        self._resources = resources   # canonical -> _ResourceInfo

    def canonicalize(self, name: str) -> str:
        """Resolve any name variation to its canonical form.

        Returns the input unchanged for unknown names.
        """
        return self._lookup.get(name, self._lookup.get(_normalize(name), name))

    def aliases(self, canonical: str) -> set[str]:
        """Return all known aliases for a canonical resource."""
        info = self._resources.get(canonical)
        if info is None:
            return set()
        return info.aliases | {canonical}

    def parent(self, canonical: str) -> str | None:
        """Return the parent resource from path nesting."""
        info = self._resources.get(canonical)
        return info.parent if info else None

    def path_param(self, canonical: str) -> str | None:
        """Return the path parameter name for this resource."""
        info = self._resources.get(canonical)
        return info.path_param if info else None

    def all_resources(self) -> set[str]:
        """Return all canonical resource names."""
        return set(self._resources.keys())


def build_canonical_resource_map(spec: dict[str, Any]) -> CanonicalResourceMap:
    """Build a canonical resource map from an OpenAPI spec's paths.

    Algorithm:
    1. Parse paths, extract (resource, path_param, parent) tuples
    2. Standalone resources define canonical names
    3. Composite nested names become aliases
    4. All variations (hyphen, underscore, singular, plural) added to lookup
    """
    paths = spec.get("paths", {})
    if not paths:
        return CanonicalResourceMap({}, {})

    # Step 1: Extract resource info from all paths.
    raw_resources: dict[str, _ResourceInfo] = {}
    composite_aliases: list[tuple[str, str, str | None]] = []  # (composite, terminal, parent)

    for path_template in paths:
        segments = _split_path(path_template)
        if not segments:
            continue

        # Walk segments to find (resource, param) pairs.
        resource_chain: list[tuple[str, str | None]] = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            param_match = _PATH_PARAM_RE.match(seg)

            if param_match:
                # This is a {param} — it belongs to the previous resource
                if resource_chain:
                    res_name, _ = resource_chain[-1]
                    resource_chain[-1] = (res_name, param_match.group(1))
                i += 1
                continue

            # Skip version/api prefixes
            if seg.lower() in _SKIP_SEGMENTS or _VERSION_SEGMENT_RE.match(seg):
                i += 1
                continue

            # Static segment: this is a resource name.
            # Skip bare hyphens/underscores that normalize to empty.
            if not _normalize(seg):
                i += 1
                continue
            resource_chain.append((seg, None))
            i += 1

        # Process the resource chain.
        parent_canonical: str | None = None
        for j, (res_name, param) in enumerate(resource_chain):
            normalized = _normalize(res_name)

            # Determine if this is a composite nested name.
            if parent_canonical and j > 0:
                composite_name = _build_composite_name(parent_canonical, normalized)
                terminal = normalized
                composite_aliases.append((composite_name, terminal, parent_canonical))

            # Register standalone resource.
            if normalized not in raw_resources:
                raw_resources[normalized] = _ResourceInfo(
                    canonical=normalized,
                    path_param=param,
                    parent=parent_canonical,
                )
            else:
                # Update path_param if we found one and didn't have one.
                if param and not raw_resources[normalized].path_param:
                    raw_resources[normalized].path_param = param
                # Update parent if we don't have one yet.
                if parent_canonical and not raw_resources[normalized].parent:
                    raw_resources[normalized].parent = parent_canonical

            parent_canonical = normalized

    # Step 2: Resolve composite aliases.
    for composite, terminal, parent in composite_aliases:
        # Check if the terminal resource exists as a standalone.
        canonical_terminal = _find_canonical(terminal, raw_resources)

        if canonical_terminal and canonical_terminal in raw_resources:
            # Check prefix relationship: only strip if parent name prefixes terminal
            parent_stem = _singularize(parent) if parent else ""
            if parent_stem and terminal.startswith(parent_stem):
                # Parent prefixes terminal — alias composite to the standalone canonical
                raw_resources[canonical_terminal].aliases.add(composite)
            else:
                # No prefix relationship — register composite as separate resource
                # but still alias to standalone if one exists
                raw_resources[canonical_terminal].aliases.add(composite)
        else:
            # No standalone version — the composite IS the canonical
            if composite not in raw_resources:
                raw_resources[composite] = _ResourceInfo(
                    canonical=composite,
                    parent=parent,
                )

    # Step 3: Build the lookup dict with all variations.
    lookup: dict[str, str] = {}
    for canonical, info in raw_resources.items():
        _register_variations(lookup, canonical, canonical)
        for alias in info.aliases:
            _register_variations(lookup, alias, canonical)

    return CanonicalResourceMap(lookup, raw_resources)


def _split_path(path: str) -> list[str]:
    """Split a path template into non-empty segments."""
    return [s for s in path.strip("/").split("/") if s]


def _normalize(name: str) -> str:
    """Normalize a resource name: lowercase, replace underscores with hyphens."""
    return name.lower().replace("_", "-").strip("-")


def _singularize(name: str) -> str:
    """Singularize a resource name."""
    if not name:
        return name
    result = _engine.singular_noun(name)
    return result if result else name


def _build_composite_name(parent: str, child: str) -> str:
    """Build a composite name like 'instances-instance-groups'."""
    return f"{parent}-{child}"


def _find_canonical(name: str, resources: dict[str, _ResourceInfo]) -> str | None:
    """Find the canonical name for a resource, checking exact and variations."""
    if not name:
        return None
    if name in resources:
        return name
    # Try singular/plural
    singular = _singularize(name)
    if singular in resources:
        return singular
    plural = _engine.plural_noun(name)
    if plural and plural in resources:
        return plural
    return None


def _register_variations(
    lookup: dict[str, str], name: str, canonical: str,
) -> None:
    """Register all variations of a name in the lookup dict."""
    normalized = _normalize(name)

    # Don't overwrite existing entries (first registration wins).
    for variation in _all_forms(normalized):
        if variation not in lookup:
            lookup[variation] = canonical

    # Also register the raw name.
    if name not in lookup:
        lookup[name] = canonical
    raw_lower = name.lower()
    if raw_lower not in lookup:
        lookup[raw_lower] = canonical


def _all_forms(normalized: str) -> list[str]:
    """Generate all form variations: as-is, singular, plural, underscore."""
    if not normalized:
        return []
    forms = [normalized]

    # Underscore variant
    underscore = normalized.replace("-", "_")
    if underscore != normalized:
        forms.append(underscore)

    # Singular
    singular = _singularize(normalized)
    if singular != normalized:
        forms.append(singular)
        forms.append(singular.replace("-", "_"))

    # Plural
    plural = _engine.plural_noun(normalized)
    if plural and plural != normalized:
        forms.append(plural)
        forms.append(plural.replace("-", "_"))

    return forms


# ── FK suffix learning ─────────────────────────────────────────────────


def learn_fk_suffixes(
    spec: dict[str, Any],
    canonical_map: CanonicalResourceMap,
) -> tuple[str, ...]:
    """Learn FK suffix conventions from the spec's path parameters.

    Examines all path parameter names across the spec, strips resource-name
    prefixes to extract suffixes (e.g., ``user_id`` -> ``_id``), and returns
    suffixes that appear frequently enough to be conventions.

    Threshold: suffix appears in >30% of path params OR in 2+ distinct params.
    For specs with <3 path params, returns bare stem-based suffixes only.
    """
    paths = spec.get("paths", {})
    if not paths:
        return ()

    # Collect (param_name, adjacent_resource) pairs.
    param_resource_pairs: list[tuple[str, str | None]] = []

    for path_template in paths:
        segments = _split_path(path_template)
        prev_resource: str | None = None
        for seg in segments:
            m = _PATH_PARAM_RE.match(seg)
            if m:
                param_resource_pairs.append((m.group(1), prev_resource))
            elif seg.lower() not in _SKIP_SEGMENTS and not _VERSION_SEGMENT_RE.match(seg):
                prev_resource = _normalize(seg)

    if not param_resource_pairs:
        return ()

    # Extract suffixes.
    suffix_counts: dict[str, int] = {}
    for param_name, resource in param_resource_pairs:
        param_lower = param_name.lower()

        # Try stripping the resource name prefix.
        suffix = None
        if resource:
            # Try singular form of resource as prefix.
            res_singular = _singularize(resource).replace("-", "_")
            res_norm = resource.replace("-", "_")
            for prefix in (res_singular, res_norm, resource):
                if param_lower.startswith(prefix) and len(param_lower) > len(prefix):
                    suffix = param_lower[len(prefix):]
                    if not suffix.startswith("_"):
                        suffix = "_" + suffix
                    break

        # Handle bare stems: if param IS a bare word (no underscore, short),
        # treat "_" + param as a suffix.
        if suffix is None and "_" not in param_lower and len(param_lower) <= 8:
            suffix = "_" + param_lower

        if suffix:
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1

    if not suffix_counts:
        return ()

    total_params = len(param_resource_pairs)

    # Apply threshold: >30% of params OR 2+ distinct occurrences.
    learned: list[tuple[str, int]] = []
    for suffix, count in suffix_counts.items():
        proportion = count / total_params if total_params > 0 else 0
        if count >= 2 or proportion > 0.3:
            learned.append((suffix, count))

    # Sort by frequency (most common first).
    learned.sort(key=lambda x: -x[1])
    return tuple(s for s, _ in learned)
