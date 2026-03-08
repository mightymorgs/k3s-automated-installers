"""Template reference detection for template sidecar generation."""

from __future__ import annotations

import re
from pathlib import Path

_SRC_PATTERN = re.compile(r'src:\s*["\']?(.+\.j2)["\']?', re.MULTILINE)


def detect_template_refs(playbook_path: Path) -> list[str]:
    """Detect Jinja2 template src references from a playbook file."""
    content = playbook_path.read_text()
    refs: list[str] = []

    for match in _SRC_PATTERN.finditer(content):
        refs.append(match.group(1).strip().rstrip('"').rstrip("'"))

    return refs

