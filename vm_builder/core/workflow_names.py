"""Canonical GitHub Actions workflow name registry.

Single source of truth for all workflow filenames triggered by vm-builder.
Names MUST match the actual .github/workflows/ filenames in the repo.
"""


class WorkflowNames:
    """Registry of GitHub Actions workflow filenames.

    These values must match the actual workflow files checked into
    ``.github/workflows/``.  Run ``gh workflow list`` to verify.
    """

    # --- Install pipeline (phase-numbered, sequential) ---
    HYPERVISOR_SETUP = "phase0-hypervisor-setup.yml"
    PHASE2_PROVISION_VM = "phase2-provision-vm.yml"
    PHASE2_PROVISION_VM_GCP = "phase2-provision-vm-gcp.yml"
    PHASE2_5_SELF_BOOTSTRAP = "phase2.5-vm-self-bootstrap.yml"
    PHASE3_DEPLOY_APPS = "phase3-dynamic.yml"
    PHASE4_CONFIGURE_APPS = "phase4-dynamic.yml"
    PHASE5_DEPLOY_INGRESS_SSO = "phase5-deploy-ingress-sso.yml"

    # --- Per-app lifecycle workflows ---
    DESTROY_VM = "destroy-vm.yml"
    UNINSTALL_APP = "uninstall-app.yml"
    LIVE_CONFIG_UPDATE = "live-config-update.yml"

    # --- Planned per-app workflows (referenced in code, not yet in repo) ---
    INSTALL_APP = "install-app.yml"
    CONFIGURE_APP = "configure-app.yml"

    # --- Platform -> provision workflow mapping ---
    _PROVISION_MAP: dict[str, str] = {
        "libvirt": PHASE2_PROVISION_VM,
        "gcp": PHASE2_PROVISION_VM_GCP,
    }

    @classmethod
    def provision(cls, platform: str) -> str:
        """Return the provision workflow filename for a platform.

        Args:
            platform: Target platform (e.g., "libvirt", "gcp").

        Returns:
            Workflow filename string.

        Raises:
            ValueError: If platform has no registered provision workflow.
        """
        wf = cls._PROVISION_MAP.get(platform)
        if wf is None:
            supported = ", ".join(sorted(cls._PROVISION_MAP.keys()))
            raise ValueError(
                f"Unsupported platform: {platform}. Supported: {supported}"
            )
        return wf

    @classmethod
    def all_workflows(cls) -> list[str]:
        """Return list of all registered workflow filenames."""
        return [
            v for k, v in vars(cls).items()
            if isinstance(v, str) and v.endswith(".yml") and not k.startswith("_")
        ]

    @classmethod
    def install_workflows(cls) -> list[str]:
        """Return only the install-phase workflows, in phase order."""
        wfs = [
            v for k, v in vars(cls).items()
            if isinstance(v, str)
            and v.startswith("phase")
            and not k.startswith("_")
        ]
        return sorted(wfs)
