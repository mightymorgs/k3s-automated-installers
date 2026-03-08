"""Registry JSON write helper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_registry(registry: dict[str, Any], output_path: Path) -> None:
    """Write registry document to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, indent=2))
