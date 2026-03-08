"""SSH key generation for VM service."""

from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path


def generate_ssh_keypair(self, vm_name: str) -> tuple[str, str]:
    """Generate ed25519 SSH keypair."""
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / f"vm-key-{vm_name}"
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(key_path),
                "-N",
                "",
                "-C",
                f"vm-{vm_name}",
            ],
            check=True,
            capture_output=True,
        )
        private_key = key_path.read_text()
        public_key = key_path.with_suffix(".pub").read_text().strip()
        private_key_b64 = base64.b64encode(private_key.encode()).decode()
        return public_key, private_key_b64
