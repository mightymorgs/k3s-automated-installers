"""K3s worker drain helper."""

from __future__ import annotations

import subprocess


def drain_k3s_node(self, worker_name: str, master_name: str) -> bool:
    """Drain a K3s worker node via the master before destruction."""
    try:
        master_inventory = self.get_vm(master_name)
        tailscale_ip = master_inventory.get("_state", {}).get("tailscale_ip")
        if not tailscale_ip:
            return False

        ssh_user = master_inventory.get("ssh", {}).get("user")
        if not ssh_user:
            return False

        subprocess.run(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=10",
                f"{ssh_user}@{tailscale_ip}",
                f"kubectl drain {worker_name} "
                f"--ignore-daemonsets --delete-emptydir-data --force --timeout=120s",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=150,
        )

        subprocess.run(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=10",
                f"{ssh_user}@{tailscale_ip}",
                f"kubectl delete node {worker_name}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        return True
    except Exception:
        return False
