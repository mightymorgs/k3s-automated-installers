"""Pydantic models shared by CLI and API layers."""

from __future__ import annotations

from vm_builder.core.models_parts.app_batch import (
    AppStatus,
    AppStatusEnum,
    AppUninstallResult,
    BatchAppInstallRequest,
    BatchAppInstallResult,
    InstalledApp,
)
from vm_builder.core.models_parts.app_workflows import (
    AppConfigureRequest,
    AppConfigureResult,
    AppInstallRequest,
    AppInstallResult,
)
from vm_builder.core.models_parts.config import (
    AppConfigResponse,
    ConfigUpdateRequest,
)
from vm_builder.core.models_parts.hypervisor import (
    BootstrapScriptResult,
    HypervisorConfig,
    HypervisorSummary,
    Phase0TriggerRequest,
    Phase0TriggerResult,
)
from vm_builder.core.models_parts.ingress import (
    IngressValidateRequest,
    IngressValidateResult,
)
from vm_builder.core.models_parts.network_shares import (
    InventoryMount,
    InventoryStorageBlock,
    NetworkShare,
    NetworkShareCredentials,
    NetworkSharesConfig,
)
from vm_builder.core.models_parts.prerequisites import PrereqResult
from vm_builder.core.models_parts.refresh import RefreshResult, RefreshStatus
from vm_builder.core.models_parts.secrets import (
    AnsibleSecrets,
    BWSConfig,
    CloudflareSecrets,
    ConsoleSecrets,
    GitHubSecrets,
    HashiCorpSecrets,
    SecretStatus,
    SecretWriteResult,
    SecretWriteStatus,
    SharedSecrets,
    TailscaleSecrets,
    TerraformSecrets,
)
from vm_builder.core.models_parts.storage import (
    StorageBrowseResult,
    StorageMount,
    StorageVerifyRequest,
    StorageVerifyResult,
)
from vm_builder.core.models_parts.vm import (
    PhaseRunResult,
    VmCreateRequest,
    VmCreateResult,
    VmDeployResult,
    VmHealthStatus,
    VmSummary,
    VmUpdateRequest,
    VmUpdateResult,
    WorkerCreateRequest,
)

__all__ = [
    "AnsibleSecrets",
    "AppConfigResponse",
    "AppConfigureRequest",
    "AppConfigureResult",
    "AppInstallRequest",
    "AppInstallResult",
    "AppStatus",
    "AppStatusEnum",
    "AppUninstallResult",
    "BatchAppInstallRequest",
    "BWSConfig",
    "BatchAppInstallResult",
    "BootstrapScriptResult",
    "CloudflareSecrets",
    "ConfigUpdateRequest",
    "ConsoleSecrets",
    "GitHubSecrets",
    "HashiCorpSecrets",
    "HypervisorConfig",
    "HypervisorSummary",
    "IngressValidateRequest",
    "IngressValidateResult",
    "InstalledApp",
    "InventoryMount",
    "InventoryStorageBlock",
    "NetworkShare",
    "NetworkShareCredentials",
    "NetworkSharesConfig",
    "Phase0TriggerRequest",
    "Phase0TriggerResult",
    "PhaseRunResult",
    "PrereqResult",
    "RefreshResult",
    "RefreshStatus",
    "SecretStatus",
    "SecretWriteResult",
    "SecretWriteStatus",
    "SharedSecrets",
    "StorageBrowseResult",
    "StorageMount",
    "StorageVerifyRequest",
    "StorageVerifyResult",
    "TailscaleSecrets",
    "TerraformSecrets",
    "VmCreateRequest",
    "VmCreateResult",
    "VmDeployResult",
    "VmHealthStatus",
    "VmSummary",
    "VmUpdateRequest",
    "VmUpdateResult",
    "WorkerCreateRequest",
]
