"""Path normalization for skill operation paths.

Provides ``normalize_op_path()`` which strips .md extensions and validates
that operation paths have exactly 3 segments (service/resource/operation).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_MD_SUFFIX_RE = re.compile(r"\.md$", re.IGNORECASE)


def normalize_op_path(path: str) -> str:
    """Normalize an operation path by removing .md extension if present.

    Logs a warning if .md was stripped (migration case).

    Args:
        path: Operation path like ``"service/resource/operation"`` or
              ``"service/resource/operation.md"``.

    Returns:
        Normalized path without .md extension, lowercased, with exactly
        3 segments (``service/resource/operation``).

    Raises:
        ValueError: If *path* is empty, None, or does not contain exactly
            3 slash-separated segments after normalization.

    Examples:
        >>> normalize_op_path("authentik/oauth2/create")
        'authentik/oauth2/create'
        >>> normalize_op_path("authentik/oauth2/create.md")  # logs warning
        'authentik/oauth2/create'
    """
    if not path or not path.strip():
        raise ValueError("path must not be empty or None")

    cleaned = path.strip().lower()

    # Strip leading/trailing slashes so "/a/b/c/" becomes "a/b/c"
    cleaned = cleaned.strip("/")

    # Strip .md suffix
    had_md = bool(_MD_SUFFIX_RE.search(cleaned))
    if had_md:
        cleaned = _MD_SUFFIX_RE.sub("", cleaned)
        logger.warning(
            "Stripped .md extension from operation path '%s' "
            "(legacy v1 markdown format — should be migrated)",
            path.strip(),
        )

    # Validate segment count
    segments = cleaned.split("/")
    if len(segments) != 3:
        raise ValueError(
            f"operation path must have 3 segments "
            f"(service/resource/operation), got {len(segments)}: '{cleaned}'"
        )

    return cleaned
