"""Domain error classes for the VM builder.

All domain errors inherit from VmBuilderError. Each carries:
- status_code: HTTP status code for the response
- code: Machine-readable error code (e.g., VM_NOT_FOUND)
- category: Error family (validation, not_found, connection, dependency, auth, internal)
- hint: Optional actionable suggestion for the user
- context: Optional dict of structured key-value pairs
"""


class VmBuilderError(Exception):
    """Base error for all VM builder domain errors."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    category: str = "internal"
    hint: str | None = None

    def __init__(
        self,
        message: str,
        *,
        context: dict | None = None,
        hint: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.context = context or {}
        if hint is not None:
            self.hint = hint


# --- Validation ---

class ValidationError(VmBuilderError):
    status_code = 400
    code = "VALIDATION_ERROR"
    category = "validation"


# --- Not Found ---

class VmNotFoundError(VmBuilderError):
    status_code = 404
    code = "VM_NOT_FOUND"
    category = "not_found"
    hint = "Check the VM name in your inventory"


class HypervisorNotFoundError(VmBuilderError):
    status_code = 404
    code = "HYPERVISOR_NOT_FOUND"
    category = "not_found"
    hint = "Verify the hypervisor exists in BWS"


class AppNotFoundError(VmBuilderError):
    status_code = 404
    code = "APP_NOT_FOUND"
    category = "not_found"
    hint = "Run a registry sync to refresh available apps"


class RemotePathNotFoundError(VmBuilderError):
    status_code = 404
    code = "REMOTE_PATH_NOT_FOUND"
    category = "not_found"
    hint = "Verify the path exists on the hypervisor"


# --- Connection ---

class SshConnectionError(VmBuilderError):
    status_code = 502
    code = "SSH_CONNECTION_FAILED"
    category = "connection"
    hint = "Check that the host is reachable and SSH keys are configured"


class TailscaleError(VmBuilderError):
    status_code = 502
    code = "TAILSCALE_ERROR"
    category = "connection"
    hint = "Verify Tailscale is running and the device is online"


class StorageConnectionError(VmBuilderError):
    status_code = 502
    code = "STORAGE_CONNECTION_FAILED"
    category = "connection"
    hint = "Verify the NFS/SMB server is reachable from the hypervisor"


# --- Dependencies ---

class DependencyError(VmBuilderError):
    status_code = 409
    code = "DEPENDENCY_UNSATISFIED"
    category = "dependency"
    hint = "Install required dependencies first"


# --- Auth / Prerequisites ---

class BwsNotAvailableError(VmBuilderError):
    status_code = 503
    code = "BWS_UNAVAILABLE"
    category = "auth"
    hint = "Install BWS CLI: brew install bws"


class BwsSecretError(VmBuilderError):
    status_code = 500
    code = "BWS_SECRET_ERROR"
    category = "auth"
    hint = "Check BWS_ACCESS_TOKEN is set and valid"


class GhNotAvailableError(VmBuilderError):
    status_code = 503
    code = "GH_UNAVAILABLE"
    category = "auth"
    hint = "Install and authenticate: brew install gh && gh auth login"


class WorkflowTriggerError(VmBuilderError):
    status_code = 502
    code = "WORKFLOW_TRIGGER_FAILED"
    category = "connection"
    hint = "Check GitHub Actions permissions and runner availability"


class RegistrySyncError(VmBuilderError):
    status_code = 503
    code = "REGISTRY_SYNC_FAILED"
    category = "internal"
    hint = "Check network connectivity and GitHub authentication"
