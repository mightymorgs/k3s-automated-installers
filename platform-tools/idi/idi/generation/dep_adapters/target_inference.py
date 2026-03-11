"""RESTler-style target resource inference from field names.

Ported from RESTler ``ApiResourceTypes.fs:191-287`` (getCandidateTypeNames,
ProducerParameterName) and ``Dependencies.fs`` findProducerWithResourceName.

Key differences from the previous implementation:

1. **No hard type gate** — confidence adjusted by type, not rejected.
2. **Two-name search** — tries last word (ProducerParameterName) and
   full normalized name (ResourceName).
3. **Container-based candidate type names** — for nested body fields,
   generates suffix subsequences from the container name.
4. **Convention-aware normalization** — auto-detects naming convention
   per component and normalizes to ``__``-separated lowercase.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from idi.generation.dep_adapters.naming import (
    _engine,
    normalize,
    normalize_id_suffix,
    singularize,
    split_words,
    stem,
)
from idi.generation.resource_namer import strip_api_version_prefix

_COMMON_FK_SUFFIXES: tuple[str, ...] = (
    "_id", "_pk", "_uuid", "_guid", "_key", "_ref",
    "_ids", "_uuids", "_guids",
    "_number", "_name", "_slug", "_flow",
)

# OWASP-derived credential parameter regex (#1).
# Matches credential-like field names that should NOT be treated as FKs.
_CREDENTIAL_PARAMS: re.Pattern = re.compile(
    r"^(client[_-]?secret|access[_-]?token|refresh[_-]?token|id[_-]?token"
    r"|token|password|passwd|secret|api[_-]?key|apikey|authorization)$",
    re.IGNORECASE,
)

# Low-priority aliases for resources that use non-obvious names.
# Only activated when the alias target exists in known_resources.
_RESOURCE_ALIASES: dict[str, str] = {
    "certificate": "certificatekeypairs",
    "certificates": "certificatekeypairs",
    "kp": "certificatekeypairs",
    "application": "core-applications",
    "applications": "core-applications",
}

# RestTestGen: qualifiable name set — bare tokens that should be qualified
# by prepending the container/parent name.  From NormalizedParameterName.java.
_QUALIFIABLE_TOKENS: frozenset[str] = frozenset({
    "id", "ids", "pk", "uuid", "name", "key", "ref", "slug",
})

_NEVER_FK_FIELDS: frozenset[str] = frozenset({
    "name", "slug", "url", "path", "type", "kind", "mode", "format",
    "description", "summary", "title", "label", "comment",
    "message", "reason", "error", "help_text", "verbose_name",
    "content", "body", "text", "notes", "detail",
    "created", "modified", "updated", "deleted",
    "enabled", "disabled", "active", "is_active",
})

_NON_FK_FORMATS: frozenset[str] = frozenset({
    "date-time", "date", "time", "duration",
    "email", "idn-email", "uri", "uri-reference",
    "iri", "iri-reference", "ipv4", "ipv6",
    "hostname", "idn-hostname", "byte", "binary", "password",
})


def infer_target(
    field_name: str,
    field_info: dict[str, Any],
    known_resources: set[str],
    *,
    container: str | None = None,
    json_path: list[str] | None = None,
) -> tuple[str | None, float]:
    """Infer target resource from a field name using RESTler-style matching.

    Returns ``(target_resource, confidence)`` or ``(None, 0.0)``.

    Args:
        field_name: The property name from the request body schema.
        field_info: The property schema dict (type, format, etc.).
        known_resources: Set of known resource names in this service.
        container: Parent property name (for nested body fields).
        json_path: Full JSON path to this field in the body schema.
    """
    # Credential exclusion (#1): skip credential-like params unless they
    # have an FK suffix (e.g. token_id, secret_id are legitimate FKs).
    fn_lower = field_name.lower()
    if not _has_fk_suffix(fn_lower) and _CREDENTIAL_PARAMS.match(fn_lower):
        return None, 0.0

    # Compute type-based confidence factor.
    type_factor = _type_factor(field_name, field_info)
    if type_factor <= 0.0:
        return None, 0.0

    # Freeze for hashing in lru_cache.
    frozen_resources = _freeze(known_resources)

    # Generate all candidate names with base confidence.
    candidates = _build_candidates(field_name, container)

    # Try ALL candidates and keep the best match.
    best: tuple[str | None, float] = (None, 0.0)
    for candidate, base_confidence in candidates:
        match = _match_resource(candidate, frozen_resources)
        if match is not None:
            resource, match_confidence = match
            confidence = base_confidence * match_confidence * type_factor
            if confidence > best[1]:
                best = (resource, confidence)
    if best[0] is not None:
        return best[0], round(best[1], 3)

    return None, 0.0


def _type_factor(field_name: str, field_info: dict[str, Any]) -> float:
    """Compute a confidence multiplier based on field type.

    RESTler has no type gate.  We use a soft gate because we lack
    endpoint-based disambiguation.
    """
    fn_lower = field_name.lower()

    # Known non-FK fields.
    if fn_lower in _NEVER_FK_FIELDS:
        return 0.0

    # --- Schema signal gates (section-03) ---
    # Enum fields are categorical, never FKs.
    if field_info.get("enum"):
        return 0.0

    # Server-generated fields can't be consumer inputs.
    if field_info.get("readOnly"):
        return 0.0

    ftype = field_info.get("type", "")
    fmt = field_info.get("format", "")

    # Non-FK formats (date-time, email, uri, etc.) — reject early.
    if fmt in _NON_FK_FORMATS:
        return 0.0

    # Pattern-constrained strings — heavily penalized but not excluded.
    if field_info.get("pattern") and ftype == "string":
        return 0.1

    # Strong FK signals.
    if ftype == "integer" or fmt == "uuid":
        return 1.0
    if ftype == "array":
        item_type = field_info.get("items", {}).get("type", "")
        if item_type in ("integer", "string"):
            return 0.9
        return 0.0

    # String fields — accept with reduced confidence.
    if ftype == "string":
        if _has_fk_suffix(fn_lower):
            return 0.8
        # Plain string: only accept if it has a reasonable name.
        return 0.5

    # Number type — some APIs use number instead of integer for FK IDs.
    if ftype == "number":
        if _has_fk_suffix(fn_lower):
            return 0.5
        return 0.0

    # Missing type — possibly unresolved $ref.  Accept with low confidence
    # when the field name is FK-like.
    if not ftype:
        if _has_fk_suffix(fn_lower):
            return 0.4
        return 0.2

    # Boolean, object, etc. — never FKs.
    return 0.0


def _has_fk_suffix(fn_lower: str) -> bool:
    """Check if a field name has a common FK suffix."""
    return any(fn_lower.endswith(s) for s in _COMMON_FK_SUFFIXES)


def _build_candidates(
    field_name: str,
    container: str | None,
) -> list[tuple[str, float]]:
    """Generate candidate resource names with base confidence.

    RESTler two-name search: ProducerParameterName (last word) and
    ResourceName (full name minus last word).
    """
    candidates: list[tuple[str, float]] = []
    words = split_words(field_name)

    if not words:
        return candidates

    # --- RESTler ProducerParameterName: last word ---
    # Used as-is for matching (e.g., accountId → "id").
    # Low confidence — just the suffix.
    producer_param = words[-1].lower()
    if len(words) > 1:
        candidates.append((producer_param, 0.3))

    # --- RESTler ResourceName: full name minus last word ---
    # accountId → "account", credential_type_id → "credential__type"
    if len(words) > 1:
        resource_name = "__".join(w.lower() for w in words[:-1])
        candidates.append((resource_name, 0.6))

    # --- Full normalized name ---
    full_normalized = normalize(field_name)
    candidates.append((full_normalized, 0.7))

    # --- FK suffix stripping ---
    fn_lower = field_name.lower()
    for suffix in _COMMON_FK_SUFFIXES:
        stripped = fn_lower.removesuffix(suffix)
        if stripped != fn_lower and stripped:
            candidates.append((normalize(stripped), 0.5))

    # --- ID synonym normalization (#8) ---
    # Normalize _uuid/_guid/_uid to _id for cross-convention matching.
    normalized = normalize_id_suffix(field_name)
    if normalized != field_name:
        # Re-run suffix stripping on the normalized form (e.g. user_uuid → user_id → user)
        norm_lower = normalized.lower()
        for suffix in _COMMON_FK_SUFFIXES:
            stripped = norm_lower.removesuffix(suffix)
            if stripped != norm_lower and stripped:
                candidates.append((normalize(stripped), 0.48))  # Slight penalty for synonym

    # --- RestTestGen name qualification ---
    # If the field name is a bare qualifiable token (id, name, key, etc.),
    # prepend the container to form a qualified candidate.
    # E.g., container="subnet", field="id" → candidate "subnet__id" → "subnet"
    if container and full_normalized in _QUALIFIABLE_TOKENS:
        qualified = normalize(container) + "__" + full_normalized
        candidates.append((qualified, 0.5))
        # Also add just the container name (since "subnet.id" means the
        # FK points to "subnets").
        candidates.append((normalize(container), 0.6))

    # --- Container-based candidate type names (for nested fields) ---
    if container:
        container_singular = singularize(container)
        container_words = split_words(container_singular)
        # All suffix subsequences (RESTler getCandidateTypeNames).
        for i in range(len(container_words)):
            type_name = "__".join(w.lower() for w in container_words[i:])
            candidates.append((type_name, max(0.3, 0.6 - i * 0.1)))
        # Remove-last + singularize variant (for 3+ word containers).
        if len(container_words) > 2:
            remove_suffix = "__".join(w.lower() for w in container_words[:-1])
            candidates.append((singularize(remove_suffix), 0.4))

    return candidates


def _freeze(resources: set[str] | frozenset[str]) -> frozenset[str]:
    """Convert to frozenset for hashing in cached lookups."""
    if isinstance(resources, frozenset):
        return resources
    return frozenset(resources)


def _match_resource(
    candidate: str,
    known_resources: frozenset[str],
) -> tuple[str, float] | None:
    """Match a normalized candidate against known resources.

    Uses convention-aware normalization so ``credential__type`` matches
    ``credential-types`` (which normalizes to ``credential__types``).
    """
    if not candidate:
        return None

    # Build a normalized lookup (cached per resource set).
    lookup = _build_resource_lookup(known_resources)

    # Exact normalized match.
    if candidate in lookup:
        return lookup[candidate], 0.7

    # Pluralize.
    plural = singularize(candidate)  # Undo singularization first.
    if plural != candidate and plural in lookup:
        return lookup[plural], 0.5

    # Try adding/removing 's'.
    if candidate + "s" in lookup:
        return lookup[candidate + "s"], 0.5
    if candidate.endswith("s") and candidate[:-1] in lookup:
        return lookup[candidate[:-1]], 0.5

    # Inflect-based plural/singular.
    inflect_plural = _engine.plural_noun(candidate)
    if inflect_plural and inflect_plural in lookup:
        return lookup[inflect_plural], 0.5
    inflect_singular = _engine.singular_noun(candidate)
    if inflect_singular and inflect_singular in lookup:
        return lookup[inflect_singular], 0.5

    # --- Flat comparison ---
    # Handles cross-convention matching: 'quality__profile' matches
    # 'qualityprofile' by stripping separator differences.
    if "__" in candidate:
        candidate_flat = candidate.replace("__", "")
        for norm_res, orig_res in sorted(
            ((nr, lookup[nr]) for nr in lookup), key=lambda x: x[0],
        ):
            res_flat = norm_res.replace("__", "")
            if candidate_flat == res_flat:
                return orig_res, 0.5
            # Also try plural/singular of flat form.
            candidate_flat_s = candidate_flat + "s"
            if candidate_flat_s == res_flat:
                return orig_res, 0.5

    # --- Porter stemming (RestTestGen-style) ---
    # Stem both candidate and resource names; exact stemmed match catches
    # cross-morphological forms that inflect misses (e.g., customize ↔ customization).
    stemmed_lookup = _build_stemmed_lookup(known_resources)
    candidate_stemmed = stem(candidate) if "__" in candidate else stem(candidate)
    if candidate_stemmed in stemmed_lookup:
        return stemmed_lookup[candidate_stemmed], 0.4

    # --- Alias lookup ---
    # Low-priority fallback for resources with non-obvious names.
    # Only activates when the alias target exists in known_resources.
    alias_target = _RESOURCE_ALIASES.get(candidate)
    if alias_target and alias_target in known_resources:
        return alias_target, 0.5

    # --- Prefix match: 'provider' matches 'providers-oauth2' ---
    # Collect ALL matches, return shortest (most specific) resource.
    prefix_matches: list[str] = []
    for norm_res, orig_res in sorted(
        ((nr, lookup[nr]) for nr in lookup), key=lambda x: x[0],
    ):
        prefix = norm_res.split("__")[0]
        if prefix == candidate or prefix == inflect_plural:
            prefix_matches.append(orig_res)
    if prefix_matches:
        # Prefer canonical listing resources (-all, -instances) over
        # sub-resources (-bindings, -tokens) for ambiguous prefix matches.
        def _prefix_sort_key(name: str) -> tuple[int, int]:
            canonical = 0 if name.endswith(("-all", "-instances")) else 1
            return (canonical, len(name))
        best = min(prefix_matches, key=_prefix_sort_key)
        return best, 0.3

    # Suffix containment: 'profile' is a suffix of 'qualityprofile'.
    # Also tries inflected plural form of the candidate.
    if len(candidate) >= 7:
        candidate_flat = candidate.replace("__", "")
        inflect_flat = _engine.plural_noun(candidate_flat) if candidate_flat else ""
        suffix_matches: list[str] = []
        for norm_res, orig_res in sorted(
            ((nr, lookup[nr]) for nr in lookup), key=lambda x: x[0],
        ):
            res_flat = norm_res.replace("__", "")
            if res_flat.endswith(candidate_flat) and candidate_flat != res_flat:
                suffix_matches.append(orig_res)
            elif (
                inflect_flat
                and res_flat.endswith(inflect_flat)
                and inflect_flat != res_flat
                # Must align with a __ word boundary in the normalized form
                # to avoid false positives like 'counts' matching 'accounts'.
                and (
                    norm_res == inflect_flat
                    or norm_res.endswith("__" + inflect_flat)
                )
            ):
                suffix_matches.append(orig_res)
            # Also check last __-segment of the resource against candidate.
            # E.g., 'source' matches 'managed__resources' because last
            # segment 'resources' is the plural of 'source'.  Guard: the
            # last segment must match candidate (or its inflected form)
            # exactly to avoid false positives.
            elif norm_res != candidate:
                last_seg = norm_res.rsplit("__", 1)[-1] if "__" in norm_res else ""
                if last_seg and (
                    last_seg == candidate_flat
                    or last_seg == inflect_flat
                    or _engine.singular_noun(last_seg) == candidate_flat
                ):
                    suffix_matches.append(orig_res)
        if suffix_matches:
            best = min(suffix_matches, key=len)
            return best, 0.2

    return None


@lru_cache(maxsize=8)
def _build_resource_lookup(
    known_resources: frozenset[str],
) -> dict[str, str]:
    """Build normalized → original resource name mapping.

    Includes stripped aliases for version-prefixed resources (e.g.,
    ``api-v2-credentials`` → ``credentials``) so that field names like
    ``credential`` can match via simple plural/singular lookup.
    """
    lookup: dict[str, str] = {}
    for res in known_resources:
        norm = normalize(res)
        lookup[norm] = res
        # Also add the raw name for exact matching.
        lookup[res] = res
        # Stripped version for version-prefixed resources.
        stripped = strip_api_version_prefix(res)
        if stripped != res:
            stripped_norm = normalize(stripped)
            if stripped_norm not in lookup:  # Don't overwrite direct matches
                lookup[stripped_norm] = res
            if stripped not in lookup:
                lookup[stripped] = res
    return lookup


@lru_cache(maxsize=8)
def _build_stemmed_lookup(
    known_resources: frozenset[str],
) -> dict[str, str]:
    """Build Porter-stemmed → original resource name mapping.

    RestTestGen-style: stem each token of the resource name and join.
    Used as a fallback when inflect-based matching fails.
    """
    lookup: dict[str, str] = {}
    for res in known_resources:
        stemmed = stem(res)
        if stemmed not in lookup:  # First resource wins (shortest name)
            lookup[stemmed] = res
        elif len(res) < len(lookup[stemmed]):
            lookup[stemmed] = res
        # Also stem the stripped version.
        stripped = strip_api_version_prefix(res)
        if stripped != res:
            stripped_stemmed = stem(stripped)
            if stripped_stemmed not in lookup:
                lookup[stripped_stemmed] = res
    return lookup
