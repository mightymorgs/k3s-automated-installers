"""Bootstrap script file writer."""

from __future__ import annotations

from pathlib import Path

from vm_builder.core.models import BootstrapScriptResult


def write_bootstrap_script(self, result: BootstrapScriptResult, output_path: str) -> str:
    """Write script to file and make executable."""
    path = Path(output_path)
    path.write_text(result.script_content)
    path.chmod(0o755)
    return str(path.resolve())
