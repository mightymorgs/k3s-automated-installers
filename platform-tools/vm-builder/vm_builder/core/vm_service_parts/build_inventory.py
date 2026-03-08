"""Inventory building for VM service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from vm_builder import bws
from vm_builder import schema as schema_mod
from vm_builder.bws import BWSError
from vm_builder.core.errors import VmNotFoundError, ValidationError as VmValidationError
from vm_builder.core.models import VmCreateRequest
from vm_builder.core.vm_service_parts.inject_platform_deps import inject_platform_deps
from vm_builder.core.vm_service_parts.populate_config import populate_config


def build_inventory(
    self,
    request: VmCreateRequest,
    console_username: str,
    ssh_public_key: str,
    ssh_private_key_b64: str,
    master_name: Optional[str] = None,
    registry_data: Optional[dict] = None,
    templates_dir: Optional[Path] = None,
) -> dict:
    """Build inventory dict from request. No I/O."""
    is_valid, components, name_errors = schema_mod.parse_vm_name(request.vm_name)
    if not is_valid:
        raise VmValidationError(
            "; ".join(name_errors),
            context={"vm_name": request.vm_name, "field": "vm_name"},
        )

    size_preset = schema_mod.get_size_preset(request.size)

    k3s_role = "none"
    if components["vmtype"] == "k3s":
        if components["subtype"] == "master":
            k3s_role = "server"
        elif components["subtype"] == "worker":
            k3s_role = "agent"

    inventory = {
        "schema_version": "v3.3",
        "identity": {
            "hostname": request.vm_name,
            "client": components["client"],
            "vmtype": components["vmtype"],
            "subtype": components["subtype"],
            "state": components["state"],
            "purpose": components["purpose"],
            "platform": components["platform"],
            "version": components["version"],
            "iac_version": request.iac_version or components["version"],
            "ansible_host": "",
        },
        "hardware": {
            "vcpu": request.vcpu or size_preset["vcpu"],
            "memory_mb": request.memory_mb or size_preset["memory_mb"],
            "disk_size_gb": request.disk_size_gb or size_preset["disk_size_gb"],
            "data_disk_size_gb": (
                request.data_disk_size_gb or size_preset.get("data_disk_size_gb", 0)
            ),
        },
        "network": {},
        "ssh": {
            "user": console_username,
            "authorized_keys": request.ssh_authorized_keys or [],
            "keypair": {
                "private_key_b64": ssh_private_key_b64,
                "public_key": ssh_public_key,
            },
        },
        "tailscale": {
            "oauth_client_id_key": "inventory/shared/secrets/tailscale/oauthclientid",
            "oauth_client_secret_key": (
                "inventory/shared/secrets/tailscale/oauthclientsecret"
            ),
            "tailnet_key": "inventory/shared/secrets/tailscale/tailnet",
            "tags": [
                f"tag:{components['client']}",
                f"tag:{components['state']}",
                f"tag:k8s-{components['subtype']}",
                "tag:service-cluster",
            ],
        },
        "k3s": {
            "role": k3s_role,
            "cluster_token": "",
        },
        "provider": {},
        "apps": {
            "selected_apps": (
                inject_platform_deps(request.apps or [], registry_data)
                if registry_data
                else (request.apps or [])
            ),
        },
        "cloudflare": {
            "api_token_key": "inventory/shared/secrets/cloudflare/apitoken",
            "account_id_key": "inventory/shared/secrets/cloudflare/accountid",
            "zone_id_key": "inventory/shared/secrets/cloudflare/zoneid",
        },
        "ingress": {
            "mode": request.ingress_mode or "nodeport",
            "app_overrides": request.ingress_app_overrides or {},
            "sso_overrides": request.sso_overrides or {},
        },
        "storage": {
            "location": request.storage_location or "",
            "mounts": request.storage_mounts or [],
            "app_paths": request.storage_app_paths or {},
        },
        "_config": {},
        "_overrides": {},
        "_state": {},
        "bootstrap": {
            "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "created_by": "vm-builder",
        },
    }

    if templates_dir is not None:
        cfg, ovr = populate_config(
            selected_apps=inventory["apps"]["selected_apps"],
            templates_dir=templates_dir,
            user_configs=request.app_configs,
        )
        inventory["_config"] = cfg
        inventory["_overrides"] = ovr

    if request.ingress_mode == "cloudflare" and request.ingress_domain:
        inventory["ingress"]["domain"] = request.ingress_domain

    if master_name:
        try:
            master_inv = bws.get_secret(f"inventory/{master_name}")
        except BWSError as exc:
            raise VmNotFoundError(str(exc), context={"vm_name": master_name}) from exc

        if not isinstance(master_inv, dict):
            raise VmNotFoundError(
                f"Master inventory is not a JSON object: {master_name}",
                context={"vm_name": master_name},
            )

        master_k3s = master_inv.get("k3s", {})
        cluster_token = master_k3s.get("cluster_token", "")
        server_url = master_k3s.get("server_url", "")

        if not cluster_token:
            raise VmValidationError(
                f"Master '{master_name}' has empty cluster_token. "
                f"Deploy the master first and persist the token.",
                context={"vm_name": master_name, "field": "cluster_token"},
                hint="Deploy the master VM first, then run persist-token",
            )

        inventory["k3s"]["cluster_token"] = cluster_token
        inventory["k3s"]["server_url"] = server_url
        inventory["k3s"]["master_name"] = master_name

    if request.platform == "libvirt":
        inventory["hardware"]["enable_gpu_passthrough"] = (
            request.enable_gpu_passthrough
            if request.enable_gpu_passthrough is not None
            else size_preset.get("enable_gpu_passthrough", False)
        )
        inventory["hardware"]["gpu_pci_address"] = request.gpu_pci_address or ""
        network_mode = request.network_mode or "nat"
        if network_mode == "nat":
            inventory["network"] = {
                "mode": "nat",
                "network_name": "default",
                "static_ipv4_cidr": "",
                "gateway": "192.168.122.1",
                "dns": request.dns or ["1.1.1.1", "8.8.8.8"],
            }
        else:
            inventory["network"] = {
                "mode": "bridge",
                "bridge": request.bridge or "br0",
                "static_ipv4_cidr": request.static_ip or "",
                "gateway": request.gateway or "192.168.0.1",
                "dns": request.dns or ["1.1.1.1", "8.8.8.8"],
            }
        inventory["provider"] = {
            "libvirt_uri": request.libvirt_uri or "qemu:///system",
            "base_image_path": (
                request.base_image_path
                or "/var/lib/libvirt/images/ubuntu-24.04-server-cloudimg-amd64.img"
            ),
            "network_mode": network_mode,
        }

    elif request.platform == "gcp":
        gcp = request.gcp or {}
        inventory["hardware"] = {
            "machine_type": gcp.get("machine_type", "e2-medium"),
            "boot_disk_size_gb": gcp.get("boot_disk_size_gb", 30),
            "boot_disk_type": gcp.get("boot_disk_type", "pd-balanced"),
            "data_disk_size_gb": gcp.get("data_disk_size_gb", 0),
            "data_disk_type": gcp.get("data_disk_type", "pd-balanced"),
        }
        inventory["network"] = {
            "network_name": gcp.get("network_name", "default"),
            "subnet_name": gcp.get("subnet_name", "default"),
            "enable_external_ip": gcp.get("enable_external_ip", True),
            "enable_static_ip": gcp.get("enable_static_ip", False),
        }
        inventory["provider"] = {"gcp": gcp}

    return inventory
