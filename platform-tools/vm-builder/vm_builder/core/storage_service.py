"""Remote storage detection and verification via SSH."""

from __future__ import annotations

from typing import Callable

from vm_builder.core.models import (
    StorageBrowseResult,
    StorageMount,
    StorageVerifyRequest,
    StorageVerifyResult,
)
from vm_builder.core.storage_service_parts import browse_path as browse_path_part
from vm_builder.core.storage_service_parts import bws_get_network_shares as bws_get_network_shares_part
from vm_builder.core.storage_service_parts import detect_mounts as detect_mounts_part
from vm_builder.core.storage_service_parts import ensure_mount as ensure_mount_part
from vm_builder.core.storage_service_parts import list_network_shares as list_network_shares_part
from vm_builder.core.storage_service_parts import list_remote_contents as list_remote_contents_part
from vm_builder.core.storage_service_parts import resolve_credentials as resolve_credentials_part
from vm_builder.core.storage_service_parts import save_network_shares as save_network_shares_part
from vm_builder.core.storage_service_parts import ssh_cmd as ssh_cmd_part
from vm_builder.core.storage_service_parts import verify_nfs as verify_nfs_part
from vm_builder.core.storage_service_parts import verify_smb as verify_smb_part
from vm_builder.core.storage_service_parts import verify_storage as verify_storage_part


class StorageService:
    """Service for remote storage detection and verification."""

    def __init__(self, hypervisor_resolver: Callable[[str], dict]) -> None:
        self._hypervisor_resolver = hypervisor_resolver

    _ssh_cmd = ssh_cmd_part.ssh_cmd

    detect_mounts = detect_mounts_part.detect_mounts
    ensure_mount = ensure_mount_part.ensure_mount
    browse_path = browse_path_part.browse_path

    verify_storage = verify_storage_part.verify_storage
    _verify_nfs = verify_nfs_part.verify_nfs
    _verify_smb = verify_smb_part.verify_smb
    _list_remote_contents = list_remote_contents_part.list_remote_contents

    _bws_get_network_shares = bws_get_network_shares_part.bws_get_network_shares
    list_network_shares = list_network_shares_part.list_network_shares
    save_network_shares = save_network_shares_part.save_network_shares
    resolve_credentials = resolve_credentials_part.resolve_credentials


__all__ = [
    "StorageBrowseResult",
    "StorageMount",
    "StorageService",
    "StorageVerifyRequest",
    "StorageVerifyResult",
]
