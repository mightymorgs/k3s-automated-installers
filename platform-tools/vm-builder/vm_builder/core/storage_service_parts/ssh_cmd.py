"""SSH command helper for StorageService."""

from __future__ import annotations

import subprocess

from vm_builder.core.errors import SshConnectionError


def ssh_cmd(
    self,
    hypervisor_name: str,
    command: str,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command on the hypervisor via SSH over Tailscale."""
    inventory = self._hypervisor_resolver(hypervisor_name)
    ssh_host = (
        inventory.get("_state", {}).get("tailscale", {}).get("ipv4")
        or inventory.get("hardware", {}).get("local_ip")
    )
    if not ssh_host:
        raise SshConnectionError(
            f"No reachable IP for hypervisor: {hypervisor_name}",
            context={"hypervisor": hypervisor_name},
        )

    ssh_user = inventory.get("ssh", {}).get("user")
    if not ssh_user:
        raise SshConnectionError(
            f"No ssh.user in inventory for hypervisor: {hypervisor_name}",
            context={"hypervisor": hypervisor_name},
        )

    try:
        return subprocess.run(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=10",
                f"{ssh_user}@{ssh_host}",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired:
        raise SshConnectionError(
            f"SSH to {hypervisor_name} ({ssh_host}) timed out after {timeout}s",
            context={"hypervisor": hypervisor_name, "ssh_host": ssh_host},
        )
    except subprocess.CalledProcessError as exc:
        raise SshConnectionError(
            f"SSH command failed on {hypervisor_name}: {exc.stderr or exc}",
            context={"hypervisor": hypervisor_name},
        )
