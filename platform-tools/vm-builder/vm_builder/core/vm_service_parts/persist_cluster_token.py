"""Persist K3s cluster token operation."""

from __future__ import annotations

import json
import subprocess

from vm_builder import bws
from vm_builder.core.errors import BwsSecretError, ValidationError as VmValidationError
from vm_builder.core.workflow_names import WorkflowNames


def persist_cluster_token(self, master_name: str) -> dict:
    """Persist K3s join token from deploy workflow into master inventory."""
    inventory_key = f"inventory/{master_name}"
    inventory = self.get_vm(master_name)

    k3s_role = inventory.get("k3s", {}).get("role", "none")
    if k3s_role != "server":
        raise VmValidationError(
            f"VM '{master_name}' is not a K3s server (role={k3s_role})",
            context={"vm_name": master_name, "k3s_role": k3s_role},
            hint="Only K3s master nodes (role=server) have cluster tokens",
        )

    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            f"--workflow={WorkflowNames.PHASE2_PROVISION_VM}",
            "--limit",
            "5",
            "--json",
            "databaseId,status,conclusion",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    runs = json.loads(result.stdout)
    completed = [run for run in runs if run.get("conclusion") == "success"]
    if not completed:
        raise VmValidationError(
            f"No successful deploy workflow found for '{master_name}'. "
            f"Deploy the master first.",
            context={"vm_name": master_name},
            hint="Deploy the master VM first before persisting the token",
        )

    run_id = completed[0]["databaseId"]

    result = subprocess.run(
        [
            "gh",
            "run",
            "view",
            str(run_id),
            "--json",
            "node_token,server_url",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    artifact_data = json.loads(result.stdout)

    node_token = artifact_data.get("node_token", "")
    server_url = artifact_data.get("server_url", "")

    if not node_token:
        raise VmValidationError(
            f"No node_token found in workflow run {run_id} artifacts. "
            f"The deploy workflow may not have outputted the token.",
            context={"vm_name": master_name, "run_id": run_id},
        )

    inventory["k3s"]["cluster_token"] = node_token
    inventory["k3s"]["server_url"] = server_url

    secrets = bws.list_secrets(filter_key=inventory_key)
    matching = [secret for secret in secrets if secret["key"] == inventory_key]
    if not matching:
        raise BwsSecretError(
            f"Cannot find BWS entry for: {inventory_key}",
            context={"vm_name": master_name, "inventory_key": inventory_key},
        )

    bws.edit_secret(matching[0]["id"], inventory)

    return {
        "persisted": True,
        "master_name": master_name,
        "cluster_token_prefix": node_token[:8],
        "server_url": server_url,
    }
