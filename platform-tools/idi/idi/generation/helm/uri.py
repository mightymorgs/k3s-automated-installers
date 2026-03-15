"""Stage 5: URI generation with percent-encoding for helmfacts:// scheme.

This is the ONLY stage that applies percent-encoding. All prior stages
use raw path segments.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from idi.generation.helm.models import HelmFact

# Encoding order matters: encode % first to prevent double-encoding
_ENCODE_MAP = [
    ("%", "%25"),   # Must be first
    (".", "%2E"),
    ("/", "%2F"),
    ("#", "%23"),
    (" ", "%20"),
]

_DECODE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_DECODE_MAP = {encoded: char for char, encoded in _ENCODE_MAP}


def encode_segment(segment: str) -> str:
    """Percent-encode a single path segment for use in helmfacts:// URIs."""
    result = segment
    for char, encoded in _ENCODE_MAP:
        result = result.replace(char, encoded)
    return result


def decode_segment(encoded: str) -> str:
    """Decode a percent-encoded path segment back to the original string."""
    def _replace(m: re.Match) -> str:
        token = m.group(0)
        return _DECODE_MAP.get(token, token)
    return _DECODE_RE.sub(_replace, encoded)


def build_uri(chart_name: str, path_segments: list[str]) -> str:
    """Build a helmfacts:// URI from chart name and raw path segments."""
    if not path_segments:
        return f"helmfacts://{chart_name}/#"

    parent_segments = path_segments[:-1]
    leaf_key = path_segments[-1]

    encoded_parent = ".".join(encode_segment(seg) for seg in parent_segments)
    encoded_leaf = encode_segment(leaf_key)

    return f"helmfacts://{chart_name}/{encoded_parent}#{encoded_leaf}"


def generate_uris(facts: list[HelmFact], chart_name: str) -> None:
    """Generate helmfacts:// URIs for all facts. Mutates facts in place."""
    for fact in facts:
        fact.uri = build_uri(chart_name, fact.path_segments)
