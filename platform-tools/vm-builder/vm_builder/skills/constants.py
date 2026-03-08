"""Constants for VM Builder skill generation."""

from __future__ import annotations

# Module path -> resource name mapping.
MODULE_RESOURCE_MAP: dict[str, str] = {
    "vm_service": "vm-service",
    "hypervisor_service": "hypervisor-service",
    "registry_service": "registry-service",
    "registry_generator": "registry-generator",
    "app_install_service": "app-install-service",
    "storage_service": "storage-service",
    "health_service": "health-service",
    "init_service": "init-service",
    "template_service": "template-service",
    "refresh_coordinator": "refresh-coordinator",
    "repo_service": "repo-service",
    "audit": "audit",
    "bws": "bws",
    "schema": "schema",
    "models": "models",
    "webhook_verify": "webhook-verify",
    "workflow_names": "workflow-names",
}

# vm_builder import prefix -> depends_on skill path prefix mapping.
IMPORT_DEPENDS_MAP: dict[str, str] = {
    "vm_builder.bws": "vm-builder/bws",
    "vm_builder.schema": "vm-builder/schema",
    "vm_builder.core.vm_service": "vm-builder/vm-service",
    "vm_builder.core.registry_service": "vm-builder/registry-service",
    "vm_builder.core.template_service": "vm-builder/template-service",
    "vm_builder.core.hypervisor_service": "vm-builder/hypervisor-service",
    "vm_builder.core.health_service": "vm-builder/health-service",
    "vm_builder.core.audit": "vm-builder/audit",
    "vm_builder.core.models": "vm-builder/models",
    "vm_builder.core.errors": "vm-builder/errors",
    "vm_builder.core.workflow_names": "vm-builder/workflow-names",
    "vm_builder.core.registry_generator": "vm-builder/registry-generator",
    "vm_builder.core.repo_service": "vm-builder/repo-service",
    "vm_builder.core.app_install_service": "vm-builder/app-install-service",
    "vm_builder.core.refresh_coordinator": "vm-builder/refresh-coordinator",
    "vm_builder.core.storage_service": "vm-builder/storage-service",
    "vm_builder.core.init_service": "vm-builder/init-service",
}

# Skip these modules/methods when building skills.
SKIP_MODULES: set[str] = {"__init__", "errors", "refresh_poller", "workflow_names"}
SKIP_METHODS: set[str] = {"__init__", "__repr__", "__str__", "__eq__", "__hash__"}

