"""Pure utility functions for skill generation.

All functions here are stateless — no ``self`` or shared mutable state.
They can be called from any generation module.
"""

import hashlib
import html
import json
import re
from typing import Any, Dict, List


# ── Hashing ───────────────────────────────────────────────────────────

def normalize_for_hash(obj: Any) -> Any:
    """Recursively sort list fields that are semantically sets.

    Fields like ``operations``, ``fields``, ``required_fields``,
    ``optional_fields``, and ``response_key_fields`` contain items whose
    ordering is not meaningful.  Sorting them ensures that logically
    identical documents produce the same canonical JSON.

    Args:
        obj: JSON-serialisable object to normalise.

    Returns:
        Normalised copy with set-like list fields sorted.
    """
    set_like_keys = {
        "operations", "fields", "required_fields",
        "optional_fields", "response_key_fields",
    }
    if isinstance(obj, dict):
        result: Dict[str, Any] = {}
        for k, v in obj.items():
            if k in set_like_keys and isinstance(v, list):
                result[k] = sorted(normalize_for_hash(v))
            else:
                result[k] = normalize_for_hash(v)
        return result
    if isinstance(obj, list):
        return [normalize_for_hash(item) for item in obj]
    return obj


def compute_json_content_hash(obj: Dict[str, Any]) -> str:
    """Compute SHA256 hash of canonical JSON (deterministic across runs).

    The hash is computed over a normalised form of the input dict:

    1. The ``content_hash`` key is excluded (self-referential).
    2. Set-like list fields are sorted.
    3. Dict keys are sorted via ``json.dumps(sort_keys=True)``.
    4. Compact separators eliminate whitespace variance.

    Args:
        obj: Dictionary to hash.

    Returns:
        Lowercase hex SHA256 digest truncated to 12 characters.
    """
    cleaned = {k: v for k, v in obj.items() if k != "content_hash"}
    normalised = normalize_for_hash(cleaned)
    canonical = json.dumps(
        normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# ── Name transformation ──────────────────────────────────────────────

def camel_to_snake(name: str) -> str:
    """Convert camelCase or PascalCase to snake_case.

    Examples:
        >>> camel_to_snake("qualityProfileId")
        'quality_profile_id'
        >>> camel_to_snake("HTTPSConnection")
        'https_connection'
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def fact_uri(service: str, resource: str, field: str) -> str:
    """Generate canonical fact URI.

    Format: ``facts://service/resource#field``

    Args:
        service: Service name.
        resource: Resource name.
        field: Field name.

    Returns:
        Canonical URI string.

    Examples:
        >>> fact_uri("authentik", "providers-oauth2", "id")
        'facts://authentik/providers-oauth2#id'
    """
    return f"facts://{service}/{resource}#{field}"


def sanitize_name(name: str) -> str:
    """Sanitise a name for use in file paths and identifiers.

    Converts to lowercase, replaces non-alphanumeric characters with
    hyphens, removes HTML entities and tags, and truncates to 50 chars.

    Args:
        name: Raw name string.

    Returns:
        Sanitised slug, or ``'default'`` if empty.
    """
    if not name:
        return "default"
    name = html.unescape(name)
    name = re.sub(r"<[^>]+>", "", name)
    name = name.replace(":", "-")
    name = name.replace(".", "-")
    name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    name = re.sub(r"-+", "-", name)
    return name[:50] if name else "default"


def clean_description(desc: str) -> str:
    """Clean HTML and special characters from a description string.

    Unescapes HTML entities, strips tags, converts common Unicode
    punctuation to ASCII, and truncates to 300 characters.

    Args:
        desc: Raw description text (may contain HTML).

    Returns:
        Cleaned plain-text description.
    """
    if not desc:
        return ""
    desc = html.unescape(desc)
    desc = re.sub(r"<[^>]+>", " ", desc)
    _unicode_replacements = {
        "\u2019": "'",  "\u2018": "'",
        "\u201c": '"',  "\u201d": '"',
        "\u2013": "-",  "\u2014": "--",
        "\u2026": "...", "\u00a0": " ",
        "\u200b": "",   "\u00b7": "-",
        "\u2022": "-",  "\u00ae": "(R)",
        "\u2122": "(TM)", "\u00a9": "(C)",
    }
    for uc, repl in _unicode_replacements.items():
        desc = desc.replace(uc, repl)
    desc = desc.encode("ascii", "ignore").decode("ascii")
    desc = re.sub(r"\s+", " ", desc).strip()
    desc = desc.lstrip(":-|>")
    return desc[:300]
