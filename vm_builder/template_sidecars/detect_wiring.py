"""BWS wiring detection for template sidecar generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Pattern: "# var_name: from BWS _state via Phase 4 extra-vars"
_EXTRA_VAR_COMMENT = re.compile(
    r"#\s+(\w+?)_(\w+):\s+from BWS _state via Phase 4 extra-vars"
)

# Pattern: inventory._state.apps.{app}.{field}
_INVENTORY_STATE = re.compile(
    r"inventory\._state\.apps\.(\w+)\.(\w+)"
)

# Pattern: ._state.apps.{app}.{field} in jq expressions (write-back)
_JQ_STATE_WRITE = re.compile(
    r"\._state\.apps\.(\w+)\.(\w+)\s*="
)


def detect_wiring(
    playbook_path: Path,
    metadata: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Detect BWS wiring (reads_from / writes_to) from a playbook.

    If ``metadata`` contains an explicit ``bws_state`` section, use that
    as the authoritative source.  Otherwise auto-detect from code patterns.
    """
    # Check for explicit bws_state metadata (highest priority)
    if metadata and "bws_state" in metadata:
        return _parse_bws_state_metadata(metadata["bws_state"])

    # Auto-detect from playbook content
    content = playbook_path.read_text()
    reads: list[dict[str, str]] = []
    writes: list[dict[str, str]] = []
    seen_reads: set[tuple[str, str]] = set()
    seen_writes: set[tuple[str, str]] = set()

    # Pattern 1: Extra-var comments
    for match in _EXTRA_VAR_COMMENT.finditer(content):
        app, field = match.group(1), match.group(2)
        if (app, field) not in seen_reads:
            reads.append({"app": app, "field": field})
            seen_reads.add((app, field))

    # Pattern 2: inventory._state.apps.{app}.{field} access
    for match in _INVENTORY_STATE.finditer(content):
        app, field = match.group(1), match.group(2)
        if (app, field) not in seen_reads:
            reads.append({"app": app, "field": field})
            seen_reads.add((app, field))

    # Pattern 3: jq ._state.apps.{app}.{field} = ... (write-back)
    for match in _JQ_STATE_WRITE.finditer(content):
        app, field = match.group(1), match.group(2)
        if (app, field) not in seen_writes:
            writes.append({"app": app, "field": field})
            seen_writes.add((app, field))

    return {"reads_from": reads, "writes_to": writes}


def _parse_bws_state_metadata(
    bws_state: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    """Parse explicit bws_state from playbook_metadata."""
    reads: list[dict[str, str]] = []
    writes: list[dict[str, str]] = []

    for entry in bws_state.get("reads", []):
        path = entry.get("path", "")
        app, field = _parse_state_path(path)
        if app and field:
            reads.append({"app": app, "field": field})

    for entry in bws_state.get("writes", []):
        path = entry.get("path", "")
        app, field = _parse_state_path(path)
        if app and field:
            writes.append({"app": app, "field": field})

    return {"reads_from": reads, "writes_to": writes}


def _parse_state_path(path: str) -> tuple[str, str]:
    """Extract (app, field) from a BWS state path.

    Example: ``_state.apps.vault.root_token`` -> ``("vault", "root_token")``
    """
    parts = path.split(".")
    try:
        apps_idx = parts.index("apps")
        if apps_idx + 2 < len(parts):
            return parts[apps_idx + 1], parts[apps_idx + 2]
    except ValueError:
        pass
    return "", ""
