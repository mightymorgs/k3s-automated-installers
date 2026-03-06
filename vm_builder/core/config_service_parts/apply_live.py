"""Apply rendered config to a live VM via kubectl over SSH."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import jinja2

from vm_builder.core.errors import (
    AppNotFoundError,
    SshConnectionError,
    ValidationError as VmValidationError,
)

logger = logging.getLogger(__name__)

_SSH_TIMEOUT = 30  # seconds
_ROLLOUT_TIMEOUT = 120  # seconds

# Fields that are immutable on a StatefulSet after creation
_STATEFULSET_IMMUTABLE_FIELDS = {"volumeClaimTemplates", "serviceName"}


def _render_template(template_path: Path, variables: dict) -> str:
    """Render a single Jinja2 template with the given variables."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_path.parent)),
        undefined=jinja2.Undefined,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(**variables)


def _get_hostname(inventory: dict) -> str:
    """Extract the VM hostname from inventory identity block."""
    hostname = inventory.get("identity", {}).get("hostname")
    if not hostname:
        raise VmValidationError(
            "VM inventory has no identity.hostname",
            hint="Ensure the VM has been provisioned and identity is set",
        )
    return hostname


def _ssh_run(hostname: str, remote_cmd: str, stdin: str = "") -> dict:
    """Run a command on the VM via SSH and return structured result."""
    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout={_SSH_TIMEOUT}",
        f"root@{hostname}",
        remote_cmd,
    ]

    try:
        result = subprocess.run(
            ssh_cmd,
            input=stdin or None,
            capture_output=True,
            text=True,
            timeout=_SSH_TIMEOUT + _ROLLOUT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise SshConnectionError(
            f"SSH to {hostname} timed out",
            context={"hostname": hostname},
        )
    except FileNotFoundError:
        raise SshConnectionError(
            "ssh command not found",
            hint="Ensure OpenSSH client is installed",
        )

    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "success": result.returncode == 0,
    }


def _kubectl_apply_via_ssh(
    hostname: str,
    manifest: str,
    namespace: str,
    dry_run: bool = False,
) -> dict:
    """Apply a manifest to the VM via SSH + kubectl."""
    cmd_parts = ["kubectl", "apply", "-f", "-", "-n", namespace]
    if dry_run:
        cmd_parts.append("--dry-run=server")

    return _ssh_run(hostname, " ".join(cmd_parts), stdin=manifest)


def _ensure_namespace(hostname: str, namespace: str) -> dict | None:
    """Check that the target namespace exists on the VM.

    Returns None if the namespace exists, or an error dict otherwise.
    """
    result = _ssh_run(
        hostname,
        f"kubectl get namespace {namespace} -o name",
    )
    if not result["success"]:
        return {
            "success": False,
            "error": f"Namespace '{namespace}' does not exist on {hostname}",
            "stderr": result["stderr"],
        }
    return None


def _detect_resource_kind(manifest: str) -> str | None:
    """Extract the ``kind:`` from a rendered YAML manifest."""
    match = re.search(r"^kind:\s*(\w+)", manifest, re.MULTILINE)
    return match.group(1) if match else None


def _detect_statefulset_warnings(manifest: str) -> list[str]:
    """Warn if a StatefulSet manifest touches immutable fields."""
    kind = _detect_resource_kind(manifest)
    if kind != "StatefulSet":
        return []

    warnings: list[str] = []
    for field in _STATEFULSET_IMMUTABLE_FIELDS:
        if field in manifest:
            warnings.append(
                f"{field} changes require StatefulSet delete+recreate "
                f"(immutable after creation)"
            )
    return warnings


def _wait_rollout(
    hostname: str,
    namespace: str,
    kind: str,
    apply_stdout: str,
) -> dict | None:
    """Wait for rollout to complete for Deployment/StatefulSet resources.

    Parses the resource name from kubectl apply stdout (e.g.
    ``deployment.apps/myapp configured``) and runs ``kubectl rollout status``.
    Returns None on success, or an error dict on failure.
    """
    if kind not in ("Deployment", "StatefulSet"):
        return None

    # kubectl apply output: "deployment.apps/myapp configured"
    kind_lower = kind.lower()
    pattern = rf"({kind_lower}[\w.]*/[\w.-]+)"
    match = re.search(pattern, apply_stdout)
    if not match:
        return None

    resource = match.group(1)
    result = _ssh_run(
        hostname,
        f"kubectl rollout status {resource} -n {namespace} --timeout={_ROLLOUT_TIMEOUT}s",
    )
    if not result["success"]:
        return {
            "rollout_error": result["stderr"] or result["stdout"],
            "resource": resource,
        }
    return None


def _detect_namespace(
    app_config: dict,
    app_id: str,
    app_dir: Path,
) -> str:
    """Detect the target namespace for an app.

    Priority: app_config.app_namespace > k8s-base/namespace.yaml > app_id.
    """
    ns = app_config.get("app_namespace")
    if ns:
        return ns

    ns_file = app_dir / "k8s-base" / "namespace.yaml"
    if ns_file.exists():
        import yaml

        try:
            data = yaml.safe_load(ns_file.read_text())
            if isinstance(data, dict):
                return data.get("metadata", {}).get("name", app_id)
        except Exception:
            pass

    return app_id


def apply_live(
    self,
    vm_name: str,
    app_id: str,
    templates_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> dict:
    """Render J2 templates and apply to the VM via kubectl over SSH.

    Connects to ``root@{hostname}`` where hostname comes from
    ``inventory.identity.hostname`` (Tailscale FQDN).

    Parameters
    ----------
    dry_run : bool
        If True, passes ``--dry-run=server`` to kubectl.
    """
    if not templates_dir:
        raise VmValidationError(
            "TEMPLATES_DIR not configured",
            context={"vm_name": vm_name, "app_id": app_id},
            hint="Set TEMPLATES_DIR environment variable",
        )

    app_dir = templates_dir / "apps" / app_id
    if not app_dir.is_dir():
        raise AppNotFoundError(
            f"App directory not found: {app_id}",
            context={"vm_name": vm_name, "app_id": app_id},
        )

    templates_subdir = app_dir / "templates"
    if not templates_subdir.is_dir():
        return {
            "app_id": app_id,
            "vm_name": vm_name,
            "results": [],
            "success": True,
            "summary": "No J2 templates found; nothing to apply",
        }

    inventory = self._vm_service.get_vm(vm_name)
    hostname = _get_hostname(inventory)
    app_config = inventory.get("_config", {}).get(app_id, {})
    namespace = _detect_namespace(app_config, app_id, app_dir)

    j2_files = sorted(templates_subdir.glob("*.j2"))
    if not j2_files:
        return {
            "app_id": app_id,
            "vm_name": vm_name,
            "results": [],
            "success": True,
            "warnings": [],
            "summary": "No J2 templates found; nothing to apply",
        }

    # Pre-check: ensure namespace exists on the target VM
    ns_err = _ensure_namespace(hostname, namespace)
    if ns_err:
        return {
            "app_id": app_id,
            "vm_name": vm_name,
            "hostname": hostname,
            "namespace": namespace,
            "dry_run": dry_run,
            "results": [],
            "success": False,
            "warnings": [],
            "summary": ns_err["error"],
        }

    results: list[dict] = []
    warnings: list[str] = []
    all_success = True

    for j2_path in j2_files:
        rendered = _render_template(j2_path, app_config)

        # Collect StatefulSet immutable-field warnings
        warnings.extend(_detect_statefulset_warnings(rendered))

        logger.info(
            "Applying %s to %s (ns=%s, dry_run=%s)",
            j2_path.name, hostname, namespace, dry_run,
        )

        apply_result = _kubectl_apply_via_ssh(
            hostname, rendered, namespace, dry_run=dry_run,
        )

        file_result = {
            "file": j2_path.name,
            "success": apply_result["success"],
            "output": apply_result["stdout"],
            "error": apply_result["stderr"] if not apply_result["success"] else "",
        }

        # Wait for rollout on successful non-dry-run applies
        if apply_result["success"] and not dry_run:
            kind = _detect_resource_kind(rendered)
            if kind:
                rollout_err = _wait_rollout(
                    hostname, namespace, kind, apply_result["stdout"],
                )
                if rollout_err:
                    file_result["error"] = rollout_err["rollout_error"]
                    file_result["success"] = False

        results.append(file_result)

        if not file_result["success"]:
            all_success = False
            logger.warning(
                "kubectl apply failed for %s: %s",
                j2_path.name, file_result["error"],
            )

    applied = sum(1 for r in results if r["success"])
    mode = "dry-run" if dry_run else "applied"

    return {
        "app_id": app_id,
        "vm_name": vm_name,
        "hostname": hostname,
        "namespace": namespace,
        "dry_run": dry_run,
        "results": results,
        "success": all_success,
        "warnings": warnings,
        "summary": f"{mode}: {applied}/{len(results)} manifests succeeded",
    }
