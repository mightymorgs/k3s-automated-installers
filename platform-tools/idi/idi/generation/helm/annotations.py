"""Stage 1 (partial): Parse structured annotations from values.yaml text.

Supports three annotation formats:
- Bitnami @param: ``## @param dotted.path [type] description``
- dadav @schema: ``# @schema key: value`` blocks
- helm-docs: ``# -- (type) description``

Slice 1 scope: single-line regex with indentation-aware next-line lookahead.
Slice 2 (section-12) adds robust find_next_yaml_key and multi-line support.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from idi.generation.helm.models import AnnotationInfo

logger = logging.getLogger(__name__)

# Max lines to scan forward from annotation to find the associated YAML key
_MAX_LOOKAHEAD = 5

# Patterns
_PARAM_RE = re.compile(r"^##\s+@param\s+(\S+)\s+\[([^\]]*)\]\s+(.*)$")
_SCHEMA_RE = re.compile(r"^#\s+@schema\s+(\w+):\s*(.*)$")
_HELMDOCS_RE = re.compile(r"^#\s+--\s+(?:\(([^)]*)\)\s+)?(.*)$")
_YAML_KEY_RE = re.compile(r"^(\s*)(\S+)\s*:")
_ARRAY_ITEM_RE = re.compile(r"^\s*-\s")
_COMMENT_OR_BLANK_RE = re.compile(r"^\s*(#|$)")


def parse_annotations(
    values_text: str,
    valid_paths: set[tuple[str, ...]],
) -> tuple[dict[tuple[str, ...], AnnotationInfo], int]:
    """Parse structured annotations from values.yaml raw text.

    Args:
        values_text: Raw values.yaml file content.
        valid_paths: Set of tuple(path_segments) that exist in parsed values.
                     Only annotations matching a valid path are returned.

    Returns:
        Tuple of (annotations_map, skipped_count).
    """
    if not values_text:
        return {}, 0

    annotations: dict[tuple[str, ...], AnnotationInfo] = {}
    skipped = 0
    lines = values_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # --- Bitnami @param ---
        m = _PARAM_RE.match(line)
        if m:
            path_str, type_str, desc = m.group(1), m.group(2), m.group(3)
            key = tuple(path_str.split("."))
            if key in valid_paths:
                annotations[key] = AnnotationInfo(
                    type=type_str.strip() or None,
                    description=desc.strip() or None,
                    enum=None,
                    source="bitnami_param",
                )
            else:
                skipped += 1
            i += 1
            continue

        # --- dadav @schema block ---
        sm = _SCHEMA_RE.match(line)
        if sm:
            schema_attrs: dict[str, str] = {}
            indent = len(line) - len(line.lstrip())
            while i < len(lines) and _SCHEMA_RE.match(lines[i]):
                attr_m = _SCHEMA_RE.match(lines[i])
                if attr_m:
                    schema_attrs[attr_m.group(1)] = attr_m.group(2).strip()
                i += 1

            # Find associated key
            yaml_key = find_next_yaml_key(lines, i, indent)
            if yaml_key is not None:
                key = (yaml_key,)
                # Parse enum if present
                enum_val = None
                if "enum" in schema_attrs:
                    try:
                        enum_val = json.loads(schema_attrs["enum"])
                        if not isinstance(enum_val, list):
                            enum_val = None
                    except (json.JSONDecodeError, TypeError):
                        pass

                if key in valid_paths:
                    annotations[key] = AnnotationInfo(
                        type=schema_attrs.get("type"),
                        description=schema_attrs.get("description"),
                        enum=enum_val,
                        source="dadav_schema",
                    )
                else:
                    skipped += 1
            else:
                skipped += 1
            continue

        # --- helm-docs ---
        hm = _HELMDOCS_RE.match(line)
        if hm:
            type_str = hm.group(1)
            desc = hm.group(2)
            indent = len(line) - len(line.lstrip())
            i += 1

            yaml_key = find_next_yaml_key(lines, i, indent)
            if yaml_key is not None:
                key = (yaml_key,)
                if key in valid_paths:
                    annotations[key] = AnnotationInfo(
                        type=type_str.strip() if type_str else None,
                        description=desc.strip() or None,
                        enum=None,
                        source="helm_docs",
                    )
                else:
                    skipped += 1
            else:
                skipped += 1
            continue

        i += 1

    return annotations, skipped


def find_next_yaml_key(
    lines: list[str],
    start_line: int,
    annotation_indent: int,
) -> str | None:
    """Find the next YAML key after an annotation comment.

    Scans forward from start_line looking for a non-comment, non-blank line
    containing ':' at the same or deeper indentation level.

    Returns the key name, or None if ambiguous/not found within MAX_LOOKAHEAD lines.
    """
    scanned = 0
    for idx in range(start_line, min(start_line + _MAX_LOOKAHEAD, len(lines))):
        line = lines[idx]

        # Skip blank and comment lines (don't count toward lookahead limit)
        if _COMMENT_OR_BLANK_RE.match(line):
            scanned += 1
            continue

        # Reject array items — don't mis-associate
        if _ARRAY_ITEM_RE.match(line):
            return None

        # Try to match a YAML key
        km = _YAML_KEY_RE.match(line)
        if km:
            key_indent = len(km.group(1))
            # Accept keys at same or deeper indent
            if key_indent >= annotation_indent:
                return km.group(2)
            return None

        # Non-comment, non-key line — ambiguous
        return None

    return None
