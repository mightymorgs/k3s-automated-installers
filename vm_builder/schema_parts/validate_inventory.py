"""Inventory validation across supported schema versions."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from vm_builder.schema_parts.parse_vm_name import parse_vm_name


def validate_inventory(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate inventory against schema v3.1, v3.2, or v3.3."""
    errors: List[str] = []

    version = data.get("schema_version")
    valid_versions = ("v3.1", "v3.2", "v3.3")

    required = [
        "schema_version",
        "identity",
        "hardware",
        "network",
        "ssh",
        "tailscale",
        "k3s",
        "apps",
        "bootstrap",
    ]
    if version in ("v3.2", "v3.3"):
        required.append("ingress")
    if version == "v3.3":
        required.append("storage")

    for key in required:
        if key not in data:
            errors.append(f"Missing required key: {key}")

    if version not in valid_versions:
        errors.append(
            f"Invalid schema version: {version}, expected one of {valid_versions}"
        )

    if "identity" in data:
        identity_required = [
            "hostname",
            "client",
            "vmtype",
            "subtype",
            "state",
            "purpose",
            "platform",
            "version",
        ]
        for key in identity_required:
            if key not in data["identity"]:
                errors.append(f"Missing identity.{key}")

        if "hostname" in data["identity"]:
            is_valid, _, name_errors = parse_vm_name(data["identity"]["hostname"])
            if not is_valid:
                errors.extend([f"identity.hostname: {error}" for error in name_errors])

    if "hardware" in data:
        hardware_required = ["vcpu", "memory_mb", "disk_size_gb"]
        for key in hardware_required:
            if key not in data["hardware"]:
                errors.append(f"Missing hardware.{key}")
            elif not isinstance(data["hardware"].get(key), int):
                errors.append(f"hardware.{key} must be an integer")

    if "network" in data:
        platform = data.get("identity", {}).get("platform", "")
        if platform == "libvirt":
            if "gateway" not in data["network"]:
                errors.append("Missing network.gateway (required for libvirt)")
            if "dns" not in data["network"]:
                errors.append("Missing network.dns (required for libvirt)")
        elif platform == "gcp":
            if "network_name" not in data["network"]:
                errors.append("Missing network.network_name (required for GCP)")

    if "ssh" in data:
        if "keypair" not in data["ssh"]:
            errors.append("Missing ssh.keypair")
        elif not isinstance(data["ssh"]["keypair"], dict):
            errors.append("ssh.keypair must be a dict")

    if "apps" in data:
        if "selected_apps" not in data["apps"]:
            errors.append("Missing apps.selected_apps (should be list)")
        elif not isinstance(data["apps"]["selected_apps"], list):
            errors.append("apps.selected_apps must be a list")
        if "config" in data["apps"] and not isinstance(data["apps"]["config"], dict):
            errors.append("apps.config must be a dict")

    if "k3s" in data:
        if "role" not in data["k3s"]:
            errors.append("Missing k3s.role")
        elif data["k3s"]["role"] not in ["server", "agent", "none"]:
            errors.append(
                "k3s.role must be 'server', 'agent', or 'none', got: "
                f"{data['k3s']['role']}"
            )

        if "cluster_token" not in data["k3s"]:
            errors.append("Missing k3s.cluster_token")

        if "server_url" in data["k3s"]:
            server_url = data["k3s"]["server_url"]
            if server_url and not isinstance(server_url, str):
                errors.append("k3s.server_url must be a string")

        if "master_name" in data["k3s"]:
            master_name = data["k3s"]["master_name"]
            if master_name and not isinstance(master_name, str):
                errors.append("k3s.master_name must be a string")
            if master_name and data["k3s"].get("role") != "agent":
                errors.append("k3s.master_name is set but k3s.role is not 'agent'")

    if "ingress" in data:
        valid_modes = ("nodeport", "tailscale", "cloudflare")
        mode = data["ingress"].get("mode")
        if mode not in valid_modes:
            errors.append(f"ingress.mode must be one of {valid_modes}, got: {mode}")
        if mode == "cloudflare" and not data["ingress"].get("domain"):
            errors.append("ingress.domain is required when mode is 'cloudflare'")
        overrides = data["ingress"].get("sso_overrides", {})
        if not isinstance(overrides, dict):
            errors.append("ingress.sso_overrides must be a dict")

    if "storage" in data:
        storage = data["storage"]
        if "location" not in storage:
            errors.append("Missing storage.location")
        if "mounts" in storage and not isinstance(storage["mounts"], list):
            errors.append("storage.mounts must be a list")
        if "app_paths" in storage and not isinstance(storage.get("app_paths", {}), dict):
            errors.append("storage.app_paths must be a dict")

    return (len(errors) == 0, errors)
